library(DatabaseConnector)
library(dplyr)

source("tools/conceptSetHelpers.R")

connectionDetails <- createConnectionDetails(
  dbms = "spark",
  connectionString = keyring::key_get("databricksConnectionString"),
  user = "token",
  password = keyring::key_get("databricksToken")
)
cdmDatabaseSchema <- "optum_extended_dod.cdm_optum_extended_dod_v4020"
options(sqlRenderTempEmulationSchema = "scratch.scratch_mschuemi")

referenceCohortDatabaseSchema <- "scratch.scratch_all"
referenceCohortProfilesTable <- "reference_cohort_profiles_optum_extended_dod_v4020"

conceptSetDatabaseSchema <- "scratch.scratch_all"
conceptSetExpressionsTable <- "concept_set_expression"
conceptSetExpressionsPlusTable <- "concept_set_expression_plus"
phenotypeToConceptSetNameTable <- "phenotype_to_concept_set"

phenotypes <- c("Acute liver failure")

# Collect all concept sets from database -------------------------------------------------------------------------------
connection <- connect(connectionDetails)

# Get phenotypeToConceptSet for selected phenotypes
# sql <- "
#     SELECT *
#     FROM @database_schema.@phenotype_to_concept_set_table
#     WHERE phenotype IN ('@phenotypes');
#   "
# phenotypeToConceptSet <- DatabaseConnector::renderTranslateQuerySql(
#   connection = connection,
#   sql = sql,
#   database_schema = conceptSetDatabaseSchema,
#   phenotype_to_concept_set_table = phenotypeToConceptSetNameTable,
#   phenotypes = paste(phenotypes, collapse = "', '"),
#   snakeCaseToCamelCase = TRUE
# )
sql <- "
    SELECT DISTINCT concept_set_expression.*
    FROM @database_schema.@concept_set_expression_table concept_set_expression
    INNER JOIN @database_schema.@phenotype_to_concept_set_table phenotype_to_concept_set
      ON phenotype_to_concept_set.concept_set_name = concept_set_expression.concept_set_name
        AND phenotype_to_concept_set.hypernym = concept_set_expression.hypernym
    WHERE phenotype IN ('@phenotypes');
  "
conceptSetExpressions <- DatabaseConnector::renderTranslateQuerySql(
  connection = connection,
  sql = sql,
  database_schema = conceptSetDatabaseSchema,
  phenotype_to_concept_set_table = phenotypeToConceptSetNameTable,
  concept_set_expression_table = conceptSetExpressionsTable,
  phenotypes = paste(phenotypes, collapse = "', '"),
  snakeCaseToCamelCase = TRUE
)

# row = conceptSetExpressions[1, ]
processConceptSet <- function(row) {
  caprWithReference <- jsonToCaprWithReference(row$conceptSetExpression, row$conceptSetName)
  conceptSetSql <- CirceR::buildConceptSetQuery(row$conceptSetExpression)
  counts <- getCounts(conceptSetSql, connection, cdmDatabaseSchema)
  
  newRow <- row |>
    select("conceptSetName", "hypernym", "conceptSetExpression") |>
    bind_cols(caprWithReference) |>
    bind_cols(counts)
  return(newRow)
}

newRows <- lapply(split(conceptSetExpressions, seq_len(nrow(conceptSetExpressions))), processConceptSet)
newRows <- bind_rows(newRows)

DatabaseConnector::insertTable(
  connection = connection,
  databaseSchema = conceptSetDatabaseSchema,
  tableName = conceptSetExpressionsPlusTable,
  data = newRows,
  createTable = TRUE,
  dropTableIfExists = TRUE,
  camelCaseToSnakeCase = TRUE,
  bulkLoad = TRUE
)
# Test is data upload did not distort data:
testData <- DatabaseConnector::renderTranslateQuerySql(
  connection = connection,
  sql = "SELECT * FROM @schema.@table;",
  schema = conceptSetDatabaseSchema,
  table = conceptSetExpressionsPlusTable,
  snakeCaseToCamelCase = TRUE
)
x1 <- newRows |>
  arrange(conceptSetName, hypernym)
x2 <- testData |>
  arrange(conceptSetName, hypernym)
if (all.equal(x1, x2, check.attributes = FALSE)) {
  message("Data uploaded correctly")
} else {
  stop("Error in conceptSetExpressions upload")
}
disconnect(connection)

# Add standard concept sets ---------------------------------------------------------------
connection <- connect(connectionDetails)

# conceptSet = standardConceptSets[[1]]
processStandardConceptSet <- function(conceptSet) {
  conceptSet <- Capr::getConceptSetDetails(conceptSet, connection, cdmDatabaseSchema)
  conceptSetExpression <- Capr::toConceptSetJson(conceptSet)
  conceptSetName <- conceptSet@Name
  caprWithReference <- jsonToCaprWithReference(conceptSetExpression, conceptSetName)
  conceptSetSql <- CirceR::buildConceptSetQuery(conceptSetExpression)
  counts <- getCounts(conceptSetSql, connection, cdmDatabaseSchema)
  
  row <- tibble(
    conceptSetName = conceptSetName,
    hypernym = 0,
    conceptSetExpression = conceptSetExpression
  ) |> 
    bind_cols(caprWithReference) |>
    bind_cols(counts)
  return(row)
}

standardConceptSets <- list(
  Capr::cs(Capr::descendants(9201), name = "Inpatient visit"),
  Capr::cs(Capr::descendants(9202), name = "Outpatient visit"),
  Capr::cs(Capr::descendants(9203, 262), name = "Emergency room visit")
)
rows <- lapply(standardConceptSets, processStandardConceptSet)
rows <- bind_rows(rows)
saveRDS(rows, "tools/StandardConceptSets.rds")

disconnect(connection)

# Upload KEEPER profiles ------------------------------------------------------------------
folder <- "../largescalephentest/AcuteLiverFailure"
keeperProfiles <- readRDS(file.path(folder, "KeeperHsc.rds"))
llmReviews <- readRDS(file.path(folder, "llmReviewsHsc.rds"))

# group = groups[[1]]
createRow <- function(group) {
  llmReview <- llmReviews |>
    filter(generatedId == group$generatedId[1])
  profileText <- Keeper:::createPrompt(Keeper::createPromptSettings(), group)
  row <- llmReview |>
    select("personId", "isCase", rationale = "justification") |>
    mutate(profile = profileText)
  return(row)
}
groups <- keeperProfiles |>
  group_by(generatedId) |>
  group_split()

rows <- lapply(groups, createRow)
rows <- bind_rows(rows)
rows$cohortDefinitionId <- 1 # TODO: connect this with reference table

connection <- connect(connectionDetails)

rows$personId <- bit64::as.integer64(rows$personId)
insertTable(
  connection = connection,
  databaseSchema = referenceCohortDatabaseSchema,
  tableName = referenceCohortProfilesTable,
  data = rows,
  dropTableIfExists = TRUE,
  createTable = TRUE,
  progressBar = TRUE,
  camelCaseToSnakeCase = TRUE
)

disconnect(connection)
