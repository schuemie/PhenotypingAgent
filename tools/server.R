# This file runs a local MCP server, providing the functions defined here to the agent. To use, configure your 
# environment to launch the MCP server, for example by adding the following the MCP.json:
# "r-tools": {
#   "command": "Rscript",
#   "args": [
#     "--vanilla",
#     "tools/server.R"
#   ]
# }
#
# Currently requires develop version of Capr: remotes::install_github("ohdsi/Capr", ref = "develop")



requiredPackages <- c("mcptools",
                      "ellmer",
                      "dplyr",
                      "CirceR",
                      "DatabaseConnector",
                      "Keeper",
                      "CohortGenerator",
                      "stringr",
                      "ParallelLogger",
                      "jsonlite",
                      "SqlRender",
                      "keyring")
missingPackages <- requiredPackages[!(requiredPackages %in% installed.packages()[,"Package"])]
if(length(missingPackages) > 0) {
  stop("Missing packages: ", paste(missingPackages, collapse = ", "))
}

library(dplyr)
library(ellmer)
library(mcptools)

source("tools/conceptSetHelpers.R")

connectionDetails <- DatabaseConnector::createConnectionDetails(
  dbms = "spark",
  connectionString = keyring::key_get("databricksConnectionString"),
  user = "token",
  password = keyring::key_get("databricksToken"),
  pathToDriver = "c:/Users/admin_mschuemi/jdbcDrivers" # .renviron is not read when running in VSCode
)
databaseName <- "Optum Clinformatics"
databaseDescription <- "Medical claims, pharmacy claims, lab test results, inpatient, and provider data. It includes electronic health data for over 126 million patients across the United States of America, beginning in 2007."
cdmDatabaseSchema <- "optum_extended_dod.cdm_optum_extended_dod_v4020"
cohortDatabaseSchema <- "scratch.scratch_mschuemi"
cohortTable <- "agent_test_cohort"
conceptSetDefinitionTable <- "agent_test_concept_set_definition"
conceptSetTable <- "agent_test_concept_set"
referenceCohortDatabaseSchema <- "scratch.scratch_all"
referenceCohortTable <- "reference_cohort_optum_extended_dod_v4020"
referenceCohortProfilesTable <- "reference_cohort_profiles_optum_extended_dod_v4020"
options(sqlRenderTempEmulationSchema = "scratch.scratch_mschuemi")

# For running Phenelope:
llmClientO3 <- ellmer::chat_azure_openai(
  endpoint = keyring::key_get("genai_openai_endpoint"),
  api_version = "2024-12-01-preview",
  model = "o3",
  credentials = function() keyring::key_get("genai_api_gpt4_key")
)
llmClient4o <- ellmer::chat_azure_openai(
  endpoint = keyring::key_get("genai_openai_endpoint"),
  api_version = "2023-03-15-preview",
  model = "gpt-4o",
  credentials = function() keyring::key_get("genai_api_gpt4_key")
)
newConceptSetsFolder <- "newConceptSets"

# Support functions and global variables -------------------------------------------------------------------------------
normalizeName <- function(name) {
  return(gsub("[^[:alnum:]]", "", tolower(name)))
}

conceptSets <- readRDS("tools/PhenelopeConceptSets.rds") |>
  mutate(normPhenotype = normalizeName(phenotype))

standardConceptSets <- readRDS("tools/StandardConceptSets.rds")

# Returns the cohort ID:
ensureCohortExists <- function(json, connection) {
  expression <- CirceR::cohortExpressionFromJson(json)
  sql <- CirceR::buildCohortQuery(expression, CirceR::createGenerateOptions(generateStats = TRUE))
  
  cohortTableNames <- CohortGenerator::getCohortTableNames(cohortTable)
  if (DatabaseConnector::existsTable(connection, cohortDatabaseSchema, cohortTable)) {
    existingCohorts <- DatabaseConnector::renderTranslateQuerySql(
      connection = connection,
      sql = "SELECT cohort_definition_id, checksum FROM @cohort_database_schema.@table;",
      cohort_database_schema = cohortDatabaseSchema,
      table = cohortTableNames$cohortChecksumTable,
      snakeCaseToCamelCase = TRUE
    )
    matchingCohortId <- existingCohorts |>
      filter(checksum ==  CohortGenerator::computeChecksum(sql)) |>
      pull(cohortDefinitionId)
    
    if (length(matchingCohortId) == 1) {
      return(matchingCohortId)
    } else {
      nextCohortId <- max(existingCohorts$cohortDefinitionId) + 1
    }
  } else {
    CohortGenerator::createCohortTables(
      connection = connection,
      cohortDatabaseSchema = cohortDatabaseSchema,
      cohortTableNames = cohortTableNames
    )
    nextCohortId <- 1
  }
  cohortDefinitionSet <- tibble(
    cohortId = nextCohortId,
    cohortName = paste("Cohort", nextCohortId),
    sql = sql,
    json = json
  )
  CohortGenerator::generateCohortSet(
    connection = connection,
    cdmDatabaseSchema = cdmDatabaseSchema,
    cohortDatabaseSchema = cohortDatabaseSchema,
    cohortTableNames = cohortTableNames,
    cohortDefinitionSet = cohortDefinitionSet,
    incremental = TRUE,
  )
  CohortGenerator::insertInclusionRuleNames(
    connection = connection,
    cohortDatabaseSchema = cohortDatabaseSchema,
    cohortDefinitionSet = cohortDefinitionSet,
    cohortInclusionTable = cohortTableNames$cohortInclusionTable
  )
  return(nextCohortId)
}

# Compile a client-supplied Capr cohort definition (R text) to Circe JSON in an isolated,
# credential-less process (Option A1 + compile-worker split). The worker validates the code
# against a strict allow-list before evaluating it; this main process — which holds the CDM
# credentials — only ever receives the compiled JSON back, and never runs the client code.
#
# Deployment note: on RStudio Connect, additionally run the worker under an OS sandbox
# (no network egress, read-only filesystem, non-root UID, CPU/memory/wall-clock limits). The
# R-level allow-list in compileWorker.R is defense-in-depth, not a complete boundary.
compileCaprViaWorker <- function(caprCode, timeoutSeconds = 60) {
  workerPath <- normalizePath(file.path("tools", "compileWorker.R"), mustWork = TRUE)
  callr::r(
    func = function(code, worker) {
      suppressPackageStartupMessages(library(Capr))
      source(worker, local = TRUE)
      validateAndCompileCapr(code)
    },
    args = list(code = caprCode, worker = workerPath),
    timeout = timeoutSeconds,
    env = callr::rcmd_safe_env(),
    show = FALSE
  )
}

compileCaprConceptSetsViaWorker <- function(caprCode, timeoutSeconds = 60) {
  workerPath <- normalizePath(file.path("tools", "compileWorker.R"), mustWork = TRUE)
  callr::r(
    func = function(code, worker) {
      suppressPackageStartupMessages(library(Capr))
      source(worker, local = TRUE)
      validateAndCompileConceptSets(code)
    },
    args = list(code = caprCode, worker = workerPath),
    timeout = timeoutSeconds,
    env = callr::rcmd_safe_env(),
    show = FALSE
  )
}

ensureConceptSetTablesExist <- function(connection) {
  sql <- "
    CREATE TABLE IF NOT EXISTS @cohort_database_schema.@definition_table (
      concept_set_hash STRING,
      concept_set_name STRING,
      concept_set_json STRING
    );

    CREATE TABLE IF NOT EXISTS @cohort_database_schema.@concept_set_table (
      concept_set_hash STRING,
      concept_id BIGINT
    );
  "
  DatabaseConnector::renderTranslateExecuteSql(
    connection = connection,
    sql = sql,
    cohort_database_schema = cohortDatabaseSchema,
    definition_table = conceptSetDefinitionTable,
    concept_set_table = conceptSetTable,
    progressBar = FALSE,
    reportOverallTime = FALSE
  )
}

quoteSqlString <- function(value) {
  paste0("'", gsub("'", "''", value, fixed = TRUE), "'")
}

ensureConceptSetsExist <- function(conceptSetsToCreate, connection) {
  ensureConceptSetTablesExist(connection)
  conceptSetsToCreate$conceptSetHash <- vapply(
    conceptSetsToCreate$json,
    CohortGenerator::computeChecksum,
    character(1)
  )

  existingHashes <- DatabaseConnector::renderTranslateQuerySql(
    connection = connection,
    sql = "SELECT concept_set_hash FROM @cohort_database_schema.@definition_table;",
    cohort_database_schema = cohortDatabaseSchema,
    definition_table = conceptSetDefinitionTable,
    snakeCaseToCamelCase = TRUE
  ) |>
    pull(conceptSetHash)

  newConceptSetRows <- which(!conceptSetsToCreate$conceptSetHash %in% existingHashes)
  for (rowIndex in newConceptSetRows) {
    conceptSetHash <- conceptSetsToCreate$conceptSetHash[rowIndex]
    conceptSetSql <- CirceR::buildConceptSetQuery(conceptSetsToCreate$json[rowIndex])
    sql <- "
      MERGE INTO @cohort_database_schema.@concept_set_table AS target
      USING (
        SELECT @concept_set_hash AS concept_set_hash, concept_id
        FROM (
          @concept_set_sql
        ) concept_set
      ) AS source
      ON target.concept_set_hash = source.concept_set_hash
        AND target.concept_id = source.concept_id
      WHEN NOT MATCHED THEN
        INSERT (concept_set_hash, concept_id)
        VALUES (source.concept_set_hash, source.concept_id);

      MERGE INTO @cohort_database_schema.@definition_table AS target
      USING (
        SELECT @concept_set_hash AS concept_set_hash,
          @concept_set_name AS concept_set_name,
          @concept_set_json AS concept_set_json
      ) AS source
      ON target.concept_set_hash = source.concept_set_hash
      WHEN NOT MATCHED THEN
        INSERT (concept_set_hash, concept_set_name, concept_set_json)
        VALUES (source.concept_set_hash, source.concept_set_name, source.concept_set_json);
    "
    DatabaseConnector::renderTranslateExecuteSql(
      connection = connection,
      sql = sql,
      cohort_database_schema = cohortDatabaseSchema,
      concept_set_table = conceptSetTable,
      definition_table = conceptSetDefinitionTable,
      concept_set_hash = quoteSqlString(conceptSetHash),
      concept_set_name = quoteSqlString(conceptSetsToCreate$name[rowIndex]),
      concept_set_json = quoteSqlString(conceptSetsToCreate$json[rowIndex]),
      concept_set_sql = SqlRender::render(
        conceptSetSql,
        vocabulary_database_schema = cdmDatabaseSchema
      ),
      progressBar = FALSE,
      reportOverallTime = FALSE
    )
  }
  return(conceptSetsToCreate)
}

getKeeperReferenceCohortId <- function(phenotype, connection) {
  if (normalizeName(phenotype) != normalizeName("Acute liver failure")) {
    stop("Currently only supporting Acute liver failure as phenotype")
  }
  # TODO: look up in reference cohort definition table:
  return(1)
}

# Tool functions --------------------------------------------------------------------------------------------------------
listConceptSets <- function(phenotype) {
  subset <- conceptSets |>
    filter(normPhenotype == normalizeName(phenotype)) |>
    bind_rows(standardConceptSets) |>
    select(conceptSetName = "target",
           overallPersons) |>
    arrange(conceptSetName)
  
  table <- c("| conceptsetName | personCount |",
             "| -------------- | ----------- |",
             sprintf("| %s | %d |",
                     subset$conceptSetName,
                     subset$overallPersons))
  table <- paste0(table, collapse = "\n")
  return(table)
}

getConceptSetsCapr <- function(phenotype, conceptSetNames, detail = "code_and_counts") {
  if (!detail %in% c("code", "code_and_counts", "full_reference")) {
    stop("The detail argument should be 'code', 'code_and_counts', or 'full_reference'")
  }
  caprWithReference <- conceptSets |>
    filter(normPhenotype == normalizeName(phenotype)) |>
    bind_rows(standardConceptSets) |>
    filter(target %in% conceptSetNames)
  
  caprWithReference <- caprWithReference |>
    group_by(target) |>
    filter(row_number() == 1) |> 
    ungroup() 
  
  caprWithReference <- caprWithReference |>
    inner_join(tibble(target = conceptSetNames,
                      order = seq_along(conceptSetNames)), by = join_by(target)) |>
    arrange(order) |>
    select(-order)
  
  columnsToInclude <- c("capr")
  if (detail %in% c("code_and_counts", "full_reference")) {
    columnsToInclude <- c(columnsToInclude, "conditionPersons", "procedurePersons", "drugPersons", "measurementPersons", "observationPersons", "visitPersons")    }
  if (detail == "full_reference") {
    columnsToInclude <- c(columnsToInclude, "conceptReference")
    caprWithReference <- caprWithReference |>
      mutate(conceptReference = paste("dummy", row_number()))
  }
  result <- caprWithReference[, columnsToInclude]
  json <- jsonlite::toJSON(result, auto_unbox = TRUE, pretty = TRUE)
  
  json <- gsub(",\n  }", "\n  }", gsub('\n[^:]+Persons": 0,?', "", json))
  
  if (detail == "full_reference") {
    for (i in seq_len(nrow(caprWithReference))) {
      json <- gsub(sprintf('"dummy %s"', i), caprWithReference$reference[i], json)
    }
  }
  return(json)
}

validateCapr <- function(caprCode) {
  result <- tryCatch({
    compileCaprViaWorker(caprCode)
    "Valid"
  },
  error = function(e) {
    return(paste("Error:", e$parent$message))
  }
  )
  return(result)
}

convertCaprToJson <- function(caprCode) {
  json <- compileCaprViaWorker(caprCode)
  
  connection <- DatabaseConnector::connect(connectionDetails)
  on.exit(DatabaseConnector::disconnect(connection))
  
  conceptIds <- stringr::str_match_all(json, '"CONCEPT_ID"\\s*:\\s*(\\d+)')[[1]][, 2] 
  conceptIds <- unique(as.integer(conceptIds))
  sql <- "
    SELECT *
    FROM @cdm_database_schema.concept
    WHERE concept_id IN (@concept_ids);
  "
  concepts <- DatabaseConnector::renderTranslateQuerySql(
    connection = connection,
    sql = sql,
    cdm_database_schema = cdmDatabaseSchema,
    concept_ids = conceptIds
  )
  colnames(concepts) <- toupper(colnames(concepts))
  concepts <- concepts |>
    mutate(STANDARD_CONCEPT_CAPTION = if_else(STANDARD_CONCEPT == "S", 
                                              "Standard", 
                                              if_else(STANDARD_CONCEPT == "C", 
                                                      "Classification",
                                                      "Non-Standard")))
  for (concept in split(concepts, concepts$CONCEPT_ID)) {
    conceptJson <- jsonlite::toJSON(concept)
    conceptJson <- gsub('\\]$', '', gsub('^\\[', '"concept": ', conceptJson))
    json <-gsub(paste0('"concept":\\s*\\{[^}]*"CONCEPT_ID"\\s*:\\s*',concept$CONCEPT_ID,'[^}]*\\}'),
                conceptJson,
                json)
  }
  
  return(json)
}

generateCohort <- function(caprCode) {
  json <- compileCaprViaWorker(caprCode)
  
  connection <- DatabaseConnector::connect(connectionDetails)
  on.exit(DatabaseConnector::disconnect(connection))   
  
  cohortId <- ensureCohortExists(json, connection)
  return(cohortId)
}

getCohortCount <- function(cohortId) {
  connection <- DatabaseConnector::connect(connectionDetails)
  on.exit(DatabaseConnector::disconnect(connection))
  
  sql <- "
      SELECT * 
      FROM @cohort_database_schema.@table 
      WHERE cohort_definition_id = @cohort_id;
    "
  inclusionRules <- DatabaseConnector::renderTranslateQuerySql(
    connection = connection,
    sql = sql,
    cohort_database_schema = cohortDatabaseSchema,
    table = CohortGenerator::getCohortTableNames(cohortTable)$cohortInclusionTable,
    cohort_id = cohortId,
    snakeCaseToCamelCase = TRUE
  ) 
  
  if (nrow(inclusionRules) > 0) {
    sql <- "
      SELECT * 
      FROM @cohort_database_schema.@table 
      WHERE cohort_definition_id = @cohort_id;
    "
    inclusionResults <- DatabaseConnector::renderTranslateQuerySql(
      connection = connection,
      sql = sql,
      cohort_database_schema = cohortDatabaseSchema,
      table = CohortGenerator::getCohortTableNames(cohortTable)$cohortInclusionResultTable,
      cohort_id = cohortId,
      snakeCaseToCamelCase = TRUE
    )
    cohortInclusionStats <- DatabaseConnector::renderTranslateQuerySql(
      connection = connection,
      sql = sql,
      cohort_database_schema = cohortDatabaseSchema,
      table = CohortGenerator::getCohortTableNames(cohortTable)$cohortInclusionStatsTable,
      cohort_id = cohortId,
      snakeCaseToCamelCase = TRUE
    )
    inclusionRules <- bind_rows(inclusionRules, 
                                tibble(cohortDefinitionId = cohortId, 
                                       ruleSequence = -1,
                                       name = "Initial event"))
    counts <- CohortGenerator::computeCohortAttrition(inclusionResults, inclusionRules) |>
      filter(modeId == 0, cohortEntry == 0) |>
      right_join(inclusionRules, by = join_by(cohortDefinitionId, ruleSequence)) |>
      select("ruleSequence", "name", incrementalPersons = "personCount")
    
    counts <- counts |>
      left_join(cohortInclusionStats |>
                  filter(modeId == 0) |>
                  select("ruleSequence", marginalPerson = "personCount", "gainCount"),
                by = join_by(ruleSequence)) |>
      mutate(ruleSequence  = ruleSequence + 1) |>
      mutate(incrementalPersons = if_else(is.na(incrementalPersons), 0, incrementalPersons),
             marginalPerson = if_else(is.na(marginalPerson) & ruleSequence != 0, 0, marginalPerson),
             gainCount = if_else(is.na(gainCount) & ruleSequence != 0, 0, gainCount)) |>
      arrange(ruleSequence)
  } else {
    sql <- "
      SELECT COUNT(DISTINCT subject_id) AS person_count, 
        COUNT(*) AS entry_count 
      FROM @cohort_database_schema.@cohort_table 
      WHERE cohort_definition_id = @cohort_id;
    "    
    counts <- DatabaseConnector::renderTranslateQuerySql(
      connection = connection,
      sql = sql,
      cohort_database_schema = cohortDatabaseSchema,
      cohort_table = cohortTable,
      cohort_id = cohortId,
      snakeCaseToCamelCase = TRUE
    )
  }
  counts <- counts |>
    mutate(database = databaseName)
  json <- jsonlite::toJSON(counts)
  return(json)
}

getDatabaseDescription <- function(databaseName) {
  return(databaseDescription)
}

countConceptSetPersonOverlap <- function(caprCode, cohortId) {
  compiledConceptSets <- compileCaprConceptSetsViaWorker(caprCode)
  conceptSetsToCount <- tibble(
    inputOrder = seq_along(compiledConceptSets),
    name = vapply(compiledConceptSets, `[[`, character(1), "name"),
    json = vapply(compiledConceptSets, `[[`, character(1), "json")
  )
  if (any(!nzchar(conceptSetsToCount$name)) || anyDuplicated(conceptSetsToCount$name)) {
    stop("Each concept set must have a non-empty, unique name")
  }

  connection <- DatabaseConnector::connect(connectionDetails)
  on.exit(DatabaseConnector::disconnect(connection))
  conceptSetsToCount <- ensureConceptSetsExist(conceptSetsToCount, connection)

  requestedConceptSets <- paste(
    sprintf(
      "SELECT %s AS concept_set_hash, %d AS input_order, %s AS concept_set_name",
      quoteSqlString(conceptSetsToCount$conceptSetHash),
      conceptSetsToCount$inputOrder,
      quoteSqlString(conceptSetsToCount$name)
    ),
    collapse = " UNION ALL "
  )
  sql <- "
    WITH requested_concept_sets AS (
      @requested_concept_sets
    ),
    cohort_persons AS (
      SELECT DISTINCT subject_id AS person_id
      FROM @cohort_database_schema.@cohort_table
      WHERE cohort_definition_id = @cohort_id
    ),
    domain_persons AS (
      SELECT DISTINCT requested.concept_set_hash, occurrence.person_id,
        'Condition' AS domain_id
      FROM requested_concept_sets requested
      INNER JOIN @cohort_database_schema.@concept_set_table concept_set
        ON requested.concept_set_hash = concept_set.concept_set_hash
      INNER JOIN @cdm_database_schema.condition_occurrence occurrence
        ON concept_set.concept_id = occurrence.condition_concept_id

      UNION ALL

      SELECT DISTINCT requested.concept_set_hash, occurrence.person_id,
        'Procedure' AS domain_id
      FROM requested_concept_sets requested
      INNER JOIN @cohort_database_schema.@concept_set_table concept_set
        ON requested.concept_set_hash = concept_set.concept_set_hash
      INNER JOIN @cdm_database_schema.procedure_occurrence occurrence
        ON concept_set.concept_id = occurrence.procedure_concept_id

      UNION ALL

      SELECT DISTINCT requested.concept_set_hash, occurrence.person_id,
        'Drug' AS domain_id
      FROM requested_concept_sets requested
      INNER JOIN @cohort_database_schema.@concept_set_table concept_set
        ON requested.concept_set_hash = concept_set.concept_set_hash
      INNER JOIN @cdm_database_schema.drug_exposure occurrence
        ON concept_set.concept_id = occurrence.drug_concept_id

      UNION ALL

      SELECT DISTINCT requested.concept_set_hash, occurrence.person_id,
        'Measurement' AS domain_id
      FROM requested_concept_sets requested
      INNER JOIN @cohort_database_schema.@concept_set_table concept_set
        ON requested.concept_set_hash = concept_set.concept_set_hash
      INNER JOIN @cdm_database_schema.measurement occurrence
        ON concept_set.concept_id = occurrence.measurement_concept_id

      UNION ALL

      SELECT DISTINCT requested.concept_set_hash, occurrence.person_id,
        'Observation' AS domain_id
      FROM requested_concept_sets requested
      INNER JOIN @cohort_database_schema.@concept_set_table concept_set
        ON requested.concept_set_hash = concept_set.concept_set_hash
      INNER JOIN @cdm_database_schema.observation occurrence
        ON concept_set.concept_id = occurrence.observation_concept_id

      UNION ALL

      SELECT DISTINCT requested.concept_set_hash, occurrence.person_id,
        'Visit' AS domain_id
      FROM requested_concept_sets requested
      INNER JOIN @cohort_database_schema.@concept_set_table concept_set
        ON requested.concept_set_hash = concept_set.concept_set_hash
      INNER JOIN @cdm_database_schema.visit_occurrence occurrence
        ON concept_set.concept_id = occurrence.visit_concept_id
    )
    SELECT requested.concept_set_hash, requested.concept_set_name,
      COUNT(DISTINCT CASE WHEN domain.domain_id = 'Condition' THEN domain.person_id END) AS condition_persons,
      COUNT(DISTINCT CASE WHEN domain.domain_id = 'Condition' AND cohort.person_id IS NOT NULL THEN domain.person_id END) AS condition_cohort_persons,
      COUNT(DISTINCT CASE WHEN domain.domain_id = 'Procedure' THEN domain.person_id END) AS procedure_persons,
      COUNT(DISTINCT CASE WHEN domain.domain_id = 'Procedure' AND cohort.person_id IS NOT NULL THEN domain.person_id END) AS procedure_cohort_persons,
      COUNT(DISTINCT CASE WHEN domain.domain_id = 'Drug' THEN domain.person_id END) AS drug_persons,
      COUNT(DISTINCT CASE WHEN domain.domain_id = 'Drug' AND cohort.person_id IS NOT NULL THEN domain.person_id END) AS drug_cohort_persons,
      COUNT(DISTINCT CASE WHEN domain.domain_id = 'Measurement' THEN domain.person_id END) AS measurement_persons,
      COUNT(DISTINCT CASE WHEN domain.domain_id = 'Measurement' AND cohort.person_id IS NOT NULL THEN domain.person_id END) AS measurement_cohort_persons,
      COUNT(DISTINCT CASE WHEN domain.domain_id = 'Observation' THEN domain.person_id END) AS observation_persons,
      COUNT(DISTINCT CASE WHEN domain.domain_id = 'Observation' AND cohort.person_id IS NOT NULL THEN domain.person_id END) AS observation_cohort_persons,
      COUNT(DISTINCT CASE WHEN domain.domain_id = 'Visit' THEN domain.person_id END) AS visit_persons,
      COUNT(DISTINCT CASE WHEN domain.domain_id = 'Visit' AND cohort.person_id IS NOT NULL THEN domain.person_id END) AS visit_cohort_persons,
      COUNT(DISTINCT domain.person_id) AS overall_persons,
      COUNT(DISTINCT CASE WHEN cohort.person_id IS NOT NULL THEN domain.person_id END) AS overall_cohort_persons
    FROM requested_concept_sets requested
    LEFT JOIN domain_persons domain
      ON requested.concept_set_hash = domain.concept_set_hash
    LEFT JOIN cohort_persons cohort
      ON domain.person_id = cohort.person_id
    GROUP BY requested.concept_set_hash, requested.concept_set_name, requested.input_order
    ORDER BY requested.input_order;
  "
  counts <- DatabaseConnector::renderTranslateQuerySql(
    connection = connection,
    sql = sql,
    requested_concept_sets = requestedConceptSets,
    cohort_database_schema = cohortDatabaseSchema,
    cohort_table = cohortTable,
    cohort_id = cohortId,
    concept_set_table = conceptSetTable,
    cdm_database_schema = cdmDatabaseSchema,
    snakeCaseToCamelCase = TRUE
  )
  return(jsonlite::toJSON(counts, auto_unbox = TRUE, pretty = TRUE))
}

evaluateCohort <- function(cohortId, phenotype) {
  connection <- DatabaseConnector::connect(connectionDetails)
  on.exit(DatabaseConnector::disconnect(connection))
  
  referenceCohortDefinitionId <- getKeeperReferenceCohortId(phenotype, connection)
  
  metrics <- Keeper::computeCohortOperatingCharacteristics(
    connection = connection,     
    cohortDatabaseSchema = cohortDatabaseSchema,
    cohortTable = cohortTable,
    cohortDefinitionId = cohortId,
    referenceCohortDatabaseSchema = referenceCohortDatabaseSchema,
    referenceCohortTableNames = Keeper::createReferenceCohortTableNames(referenceCohortTable),
    referenceCohortDefinitionId = referenceCohortDefinitionId
  )
  metrics <- metrics |>
    select("sensitivity",
           specificity = "specificityOverall",
           "ppv",
           "tp",
           "fp",
           "tn",
           "fn")
  json <- jsonlite::toJSON(metrics, pretty = TRUE)
  return(json)
}

samplePatientProfile <- function(cohortId, phenotype, type) {

  type <- tolower(type)
  if (!type %in% c("tp", "fp", "tn", "fn")) {
    return("Error: type must have value 'TP', 'FP', 'TN', or 'FN'")
  }
  
  connection <- DatabaseConnector::connect(connectionDetails)
  on.exit(DatabaseConnector::disconnect(connection))
  
  referenceCohortDefinitionId <- getKeeperReferenceCohortId(phenotype, connection)
  
  sql <- "
    SELECT CAST(subject_id AS VARCHAR) AS subject_id
    FROM (
      SELECT subject_id,
        is_case,
        MAX(has_match) AS has_match,
        MAX(within_window) as within_window
      FROM (
        SELECT reference_cohort.subject_id,
          is_case,
          CASE WHEN cohort.subject_id IS NULL THEN 0 ELSE 1 END AS has_match,
          CASE 
            WHEN DATEDIFF(DAY, reference_cohort.cohort_start_date, cohort.cohort_start_date) <= 30
              AND DATEDIFF(DAY, reference_cohort.cohort_start_date, cohort.cohort_start_date) >= -30
            THEN 1 
            ELSE 0
          END AS within_window
        FROM @reference_cohort_database_schema.@reference_cohort_table reference_cohort
        LEFT JOIN @cohort_database_schema.@cohort_table cohort
          ON reference_cohort.subject_id = cohort.subject_id
            AND cohort.cohort_definition_id = @cohort_definition_id
            AND cohort.cohort_start_date >= observation_period_start_date
            AND cohort.cohort_start_date <= observation_period_end_date
        WHERE reference_cohort.cohort_definition_id = @reference_cohort_definition_id
          AND reference_cohort.cohort_start_date IS NOT NULL
      ) tmp
      GROUP BY subject_id,
      is_case
    ) tmp2
    {@type == 'tp'} ? {WHERE is_case = 1 AND has_match = 1 AND within_window = 1;}
    {@type == 'tn'} ? {WHERE is_case = 0 AND has_match = 0;}
    {@type == 'fp'} ? {WHERE is_case = 0 AND has_match = 1 AND within_window = 1;}
    {@type == 'fn'} ? {WHERE is_case = 1 AND has_match = 0;}
  "
  personIds <- DatabaseConnector::renderTranslateQuerySql(
    connection = connection,
    sql = sql,
    reference_cohort_database_schema = referenceCohortDatabaseSchema,
    reference_cohort_table = referenceCohortTable,
    reference_cohort_definition_id = 1,
    cohort_database_schema = cohortDatabaseSchema,
    cohort_table = cohortTable,
    cohort_definition_id = cohortId,
    type = type,
    snakeCaseToCamelCase = TRUE,
  )
  if (nrow(personIds) == 0) {
    return(sprintf("No patients of type '%s' found", toupper(type)))
  }
  personId <- sample(personIds$subjectId, size = 1)
  
  sql <- "
    SELECT *
    FROM @reference_cohort_database_schema.@reference_cohort_profiles_table
    WHERE person_id = @person_id
      AND cohort_definition_id = @reference_cohort_definition_id;
  "
  profile <- DatabaseConnector::renderTranslateQuerySql(
    connection = connection,
    sql = sql,
    reference_cohort_database_schema = referenceCohortDatabaseSchema,
    reference_cohort_profiles_table = referenceCohortProfilesTable,
    reference_cohort_definition_id = 1,
    person_id = personId,
    snakeCaseToCamelCase = TRUE,
  )
  result <- list(
    type = toupper(type),
    patientProfile = profile$profile,
    rationale = profile$rationale
  )
  json <- jsonlite::toJSON(result, auto_unbox = TRUE, pretty = TRUE)
  return(json)
}

createNewConceptSet <- function(name, description) {
  outputFolder <- file.path(newConceptSetsFolder, gsub("[^[:alnum:]]", "", name))
  results <- Phenelope::createConceptSet(
    conceptName = name,
    additionalInformation = description,
    connectionDetails = connectionDetails,
    cdmDatabaseSchema = cdmDatabaseSchema,
    llmClientReasoning = llmClientO3,
    llmClientNonReasoning = llmClient4o,
    outputDirectory = outputFolder
  )
  json <- as.character(jsonlite::toJSON(results$conceptSet, auto_unbox = TRUE))
  sql <- CirceR::buildConceptSetQuery(json)
  connection <- DatabaseConnector::connect(connectionDetails)
  on.exit(DatabaseConnector::disconnect(connection))
  counts <- getCounts(sql, connection, cdmDatabaseSchema)
  capr <- jsonToCaprWithReference(json, name)
  result <- bind_cols(
    capr |>
      select(capr),
    counts
  )
  saveRDS(result, file.path(outputFolder, "mcpResult.rds"))
  resultJson <- jsonlite::toJSON(result, auto_unbox = TRUE, pretty = TRUE)
  
  resultJson <- gsub(",\n  }", "\n  }", gsub('\n[^:]+Persons": 0,?', "", resultJson))
  
  return(resultJson)
}

# Tools ----------------------------------------------------------------------------------------------------------------
listConceptSetsTool <- tool(
  listConceptSets,
  description = paste(
    "Retrieve the concept sets associated with a phenotype.",
    "Returns a markdown table with two columns: concept set name, and the number of unique persons",
    "with at least one of the concepts in the set.",
    "A count of 0 means nobody has any of the concepts."
  ),
  arguments = list(
    phenotype = type_string("Name of the phenotype for which concept sets should be returned.")
  )
)

getConceptSetsCaprTool <- tool(
  getConceptSetsCapr,
  description = paste("Returns the Capr R code for one or more concept sets, and unique person counts per domain",
                      "(only non-zero domains)."),
  arguments = list(
    phenotype = type_string("Name of the phenotype."),
    conceptSetNames = type_array(type_string("Names of the concept sets.")),
    detail = type_enum(c("code", "code_and_counts", "full_reference"), 
                       paste("Level of detail to return.",
                             "'code' returns the Capr code,",
                             "'code_and_counts' additionally returns person count per domain, and",
                             "'full_reference' also includes a reference for the concept IDs used in the code.")
    )
  )
)

validateCaprTool <- tool(
  validateCapr,
  description = "Validate the provided Capr code. Either returns 'Valid' or an informative error message.",
  arguments = list(
    caprCode = type_string(paste(
      "A single Capr cohort definition as R code: one cohort(...) expression with all concept",
      "sets inlined and no assignments. Compiled server-side — do not pass JSON."
    ))
  )
)

convertCaprToJsonTool <- tool(
  convertCaprToJson,
  description = paste("Convert Capr code to JSON, including full concept information.",
                      "(This can be a lot of text)."),
  arguments = list(
    caprCode = type_string(paste(
      "A single Capr cohort definition as R code: one cohort(...) expression with all concept",
      "sets inlined and no assignments. Compiled server-side — do not pass JSON."
    ))
  )
)

generateCohortTool <- tool(
  generateCohort,
  description = "Generate the cohort in the available database(s) and return the cohort ID.",
  arguments = list(
    caprCode = type_string(paste(
      "A single Capr cohort definition as R code: one cohort(...) expression with all concept",
      "sets inlined and no assignments. Compiled server-side — do not pass JSON."
    ))
  )
)

getCohortCountTool <- tool(
  getCohortCount,
  description = paste("Returns cohort sizes. For cohorts with attrition rules, also returns the number of persons",
                      "remaining after each rule is applied (incrementalPersons), the number of persons who satisfy",
                      "both the initial event and the rule (marginalPersons), and the number of persons that would be",
                      "added back if the rule were removed (gainCount)."),
  arguments = list(
    cohortId = type_integer("The cohort ID as returned by the `generate_cohort` tool.")
  )
)

getDatabaseDescriptionTool <- tool(
  getDatabaseDescription,
  description = "Returns a short description of a database.",
  arguments = list(
    databaseName = type_string("Name of the database.")
  )
)

countConceptSetPersonOverlapTool <- tool(
  countConceptSetPersonOverlap,
  description = paste(
    "Instantiate one or more Capr concept sets and count distinct people with their concepts",
    "in the general population and among people in a generated cohort. Returns per-domain",
    "and overall counts. Instantiated concept sets are cached by hash for reuse."
  ),
  arguments = list(
    caprCode = type_array(type_string(paste(
      "A standalone Capr cs(...) expression. Supply one or more expressions; include a",
      "name argument in each expression."
    ))),
    cohortId = type_integer("The cohort ID as returned by the `generate_cohort` tool.")
  )
)

evaluateCohortTool <- tool(
  evaluateCohort,
  description = paste(
    "Evaluate the cohort using a 10,000 person KEEPER reference cohort.",
    "Returns sensitivity, specificity (adjusted for sampling), PPV, and the confusion matrix."
  ),
  arguments = list(
    cohortId = type_integer("The cohort ID as returned by the `generate_cohort` tool."),
    phenotype = type_string("Name of the phenotype.")
  )
)

samplePatientProfileTool <- tool(
  samplePatientProfile,
  description = paste(
    "Return the patient profile and rationale for one random patient in the KEEPER reference set.",
    "Call multiple times to sample multiple patients."
  ),
  arguments = list(
    cohortId = type_integer("The cohort ID as returned by the `generate_cohort` tool."),
    phenotype = type_string("Name of the phenotype. Used to fetch the gold standard."),
    type = type_enum(c("TP", "FP", "TN", "FN"), paste(
      "Type, based on classification status, using the KEEPER reference cohort as gold standard.",
      "Options: TP, FP, TN, FN"
    ))
  )
)

createNewConceptSetTool <- tool(
  createNewConceptSet,
  description = paste("Creates a new concept set given the name and description.",
                      "Returns the Capr R code and unique person counts per domain",
                      "(only non-zero domains)."),
  arguments = list(
    name = type_string("Name of the concept set."),
    description = type_string("Description of the concept set.")
  )
)


# Start the MCP server -------------------------------------------------------------------------------------------------
mcp_server(
  tools = list(
    listConceptSetsTool,
    getConceptSetsCaprTool,
    getCohortCountTool,
    getDatabaseDescriptionTool,
    countConceptSetPersonOverlapTool,
    validateCaprTool,
    convertCaprToJsonTool,
    generateCohortTool,
    evaluateCohortTool,
    samplePatientProfileTool,
    createNewConceptSetTool
  ),
  session_tools = FALSE
)
