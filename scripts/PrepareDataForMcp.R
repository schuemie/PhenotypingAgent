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
referenceCohortDatabaseSchema <- "scratch.scratch_all"
referenceCohortTable <- "reference_cohort_optum_extended_dod_v4020"

phenotypes <- readLines("../largescalephentest/SelectedPhenotypes.txt")

maxCores <- 5

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
    SELECT concept_set_expression.*
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
  phenotypes = paste(gsub("'", "''", phenotypes), collapse = "', '"),
  snakeCaseToCamelCase = TRUE
)

# Process in parallel in batches
cacheFolder <- "e:/temp/cacheConceptSetExpression"
dir.create(cacheFolder)

# batch = batches[[1]]
processConceptSet <- function(batch, connectionDetails, cdmDatabaseSchema, cacheFolder) {
  connection <- DatabaseConnector::connect(connectionDetails)
  on.exit(DatabaseConnector::disconnect(connection))
  newRows <- list()
  for (i in seq_len(nrow(batch))) {
    fileName <- file.path(cacheFolder, sprintf("%s.rds", digest::digest(batch$conceptSetExpression[i])))
    if (file.exists(fileName)) {
      newRow <- readRDS(fileName)
    } else {
      caprWithReference <- jsonToCaprWithReference(batch$conceptSetExpression[i], batch$conceptSetName[i])
      conceptSetSql <- CirceR::buildConceptSetQuery(batch$conceptSetExpression[i])
      counts <- getCounts(conceptSetSql, connection, cdmDatabaseSchema)
      
      newRow <- batch[i, ] |>
        select("conceptSetName", "hypernym", "conceptSetExpression") |>
        bind_cols(caprWithReference) |>
        bind_cols(counts)
      saveRDS(newRow, fileName)
    }
    newRows[[i]] <- newRow
  }
  return(bind_rows(newRows))
}

batches <- conceptSetExpressions |>
  mutate(batchId = sample.int(floor(nrow(conceptSetExpressions)/25), nrow(conceptSetExpressions), replace = TRUE)) |>
  group_by(batchId) |>
  group_split()

cluster <- ParallelLogger::makeCluster(maxCores)
ParallelLogger::clusterRequire(cluster, "dplyr")
parallel::clusterExport(cluster, "jsonToCaprWithReference")
parallel::clusterExport(cluster, "getCounts")

conceptSetExpressionsPlus <- ParallelLogger::clusterApply(
  cluster = cluster,
  x = batches,
  fun = processConceptSet,
  connectionDetails = connectionDetails,
  cdmDatabaseSchema = cdmDatabaseSchema, 
  cacheFolder = cacheFolder
)
ParallelLogger::stopCluster(cluster)
conceptSetExpressionsPlus <- bind_rows(conceptSetExpressionsPlus)

DatabaseConnector::insertTable(
  connection = connection,
  databaseSchema = conceptSetDatabaseSchema,
  tableName = conceptSetExpressionsPlusTable,
  data = conceptSetExpressionsPlus,
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
x1 <- conceptSetExpressionsPlus |>
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

# Upload KEEPER profiles -----------------------------------------------------------------------------------------------
keeperFolder <- "../largescalephentest/Keeper"

cacheFolder <- "e:/temp/cacheKeeperProfilesForAgents"
dir.create(cacheFolder)

connection <- connect(connectionDetails)

referenceCohorts <- renderTranslateQuerySql(
  connection = connection,
  sql = "SELECT * FROM @database_schema.@table;",
  database_schema = referenceCohortDatabaseSchema,
  table = Keeper::createReferenceCohortTableNames(referenceCohortTable)$referenceCohortMetadataTable,
  snakeCaseToCamelCase = TRUE
)
referenceCohorts <- referenceCohorts |>
  filter(phenotype %in% phenotypes)

# row = rows[[1]]
createProfileRow <- function(row, keeperFolder, cacheFolder) {
  fileName <- file.path(cacheFolder, sprintf("%s.rds", gsub("[^[:alnum:]]+", "_", row$phenotype)))
  if (file.exists(fileName)) {
    newRows <- readRDS(fileName)
  } else {
    message("Fetching profiles for ", row$phenotype)
    phenotypeFolder <- file.path(keeperFolder, gsub("[^[:alnum:]]+", "_", row$phenotype))
    keeperProfiles <- readRDS(file.path(phenotypeFolder, "KeeperHsc.rds"))
    llmReviews <- readRDS(file.path(phenotypeFolder, "llmReviewsHsc.rds"))
    
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
    
    newRows <- lapply(groups, createRow)
    newRows <- bind_rows(newRows)
    newRows$cohortDefinitionId <- row$cohortDefinitionId
    saveRDS(newRows, fileName)
  }
  return(newRows)
}
rows <- split(referenceCohorts, seq_len(nrow(referenceCohorts)))
cluster <- ParallelLogger::makeCluster(maxCores)
ParallelLogger::clusterRequire(cluster, "dplyr")

allProfiles <- ParallelLogger::clusterApply(
  cluster = cluster,
  x = rows,
  fun = createProfileRow,
  keeperFolder = keeperFolder,
  cacheFolder = cacheFolder
)

ParallelLogger::stopCluster(cluster)

allProfiles <- bind_rows(allProfiles)

allProfiles$personId <- bit64::as.integer64(allProfiles$personId)
insertTable(
  connection = connection,
  databaseSchema = referenceCohortDatabaseSchema,
  tableName = referenceCohortProfilesTable,
  data = allProfiles,
  dropTableIfExists = TRUE,
  createTable = TRUE,
  progressBar = TRUE,
  camelCaseToSnakeCase = TRUE,
  bulkLoad = TRUE
)

disconnect(connection)
