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

# Collect all concept sets from folder ------------------------------------------------------
connection <- connect(connectionDetails)

folder <- "../largescalephentest/phenelopeConceptSets"


# target = targets[2]
processConceptSetTarget <- function(target, role, phenotype) {
  jsonFile <- file.path(folder, phenotype, role, target, sprintf("%s.json", target))
  if (!file.exists(jsonFile)) {
    # No concepts found
    return(NULL)
  }
  json <- readLines(jsonFile)  
  json <- paste(json, collapse = "\n")
  conceptSetSql <- CirceR::buildConceptSetQuery(json)
  caprWithReference <- jsonToCaprWithReference(json, target)
  
  domains <- readr::read_csv(file.path(folder, phenotype, role, target, "domains.csv"), show_col_types = FALSE)
  domains <- paste(domains$domainId, collapse = ",")
  
  counts <- getCounts(conceptSetSql, connection, cdmDatabaseSchema)
  
  row <- tibble(
    phenotype = phenotype,
    role = role,
    target = target,
    domains = domains,
    json = json,
    sql = conceptSetSql
  ) |> 
    bind_cols(caprWithReference) |>
    bind_cols(counts)
}

# role = roles[1]
processRole <- function(role, phenotype) {
  message(sprintf("- Processing %s - %s", phenotype, role))
  targets <- list.files(file.path(folder, phenotype, role))
  rows <- lapply(targets, processConceptSetTarget, role = role, phenotype = phenotype)
  rows <- bind_rows(rows)
  return(rows)
}

# phenotype = phenotypes[1]
processPhenotype <- function(phenotype) {
  roles <- list.dirs(file.path(folder, phenotype), recursive = FALSE, full.names = FALSE)
  rows <- lapply(roles, processRole, phenotype = phenotype)
  rows <- bind_rows(rows)
}

phenotypes <- list.dirs(folder, recursive = FALSE, full.names = FALSE)
rows <- lapply(phenotypes, processPhenotype)
rows <- bind_rows(rows)

object.size(rows) / 1024^2
saveRDS(rows, "tools/PhenelopeConceptSets.rds")
readr::write_csv(rows, file.path(folder, "overview.csv"))
disconnect(connection)

# Add standard concept sets ---------------------------------------------------------------
connection <- connect(connectionDetails)

# conceptSet = standardConceptSets[[1]]
processStandardConceptSet <- function(conceptSet) {
  conceptSet <- Capr::getConceptSetDetails(conceptSet, connection, cdmDatabaseSchema)
  json <- Capr::toConceptSetJson(conceptSet)
  target <- conceptSet@Name
  conceptSetSql <- CirceR::buildConceptSetQuery(json)
  caprWithReference <- jsonToCaprWithReference(json, target)

  counts <- getCounts(conceptSetSql, connection, cdmDatabaseSchema)
  
  row <- tibble(
    target = target,
    json = json,
    sql = conceptSetSql
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
