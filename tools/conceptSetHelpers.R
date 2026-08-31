# Shared helper functions used by tools/server.R and scripts/PrepareDataForMcp.R

getCounts <- function(conceptSetSql, connection, cdmDatabaseSchema) {
  sql <- "
    WITH concept_set AS (
      @concept_set_sql
    ),
    domain_persons AS (
      SELECT DISTINCT
        person_id,
        'Condition' AS domain_id
      FROM @cdm_database_schema.condition_occurrence
      WHERE condition_concept_id IN (
        SELECT concept_id
        FROM concept_set
      )
       
      UNION ALL
       
      SELECT DISTINCT
        person_id,
        'Procedure' AS domain_id
      FROM @cdm_database_schema.procedure_occurrence
      WHERE procedure_concept_id IN (
       SELECT concept_id
       FROM concept_set
      )
       
      UNION ALL
       
      SELECT DISTINCT
       person_id,
        'Drug' AS domain_id
      FROM @cdm_database_schema.drug_exposure
      WHERE drug_concept_id IN (
       SELECT concept_id
       FROM concept_set
      )
       
      UNION ALL
       
      SELECT DISTINCT
       person_id,
        'Measurement' AS domain_id
      FROM @cdm_database_schema.measurement
      WHERE measurement_concept_id IN (
        SELECT concept_id
        FROM concept_set
      )
       
      UNION ALL
       
      SELECT DISTINCT
       person_id,
       'Observation' AS domain_id
      FROM @cdm_database_schema.observation
      WHERE observation_concept_id IN (
        SELECT concept_id
        FROM concept_set
      )
      
      UNION ALL
       
      SELECT DISTINCT
       person_id,
       'Visit' AS domain_id
      FROM @cdm_database_schema.visit_occurrence
      WHERE visit_concept_id IN (
        SELECT concept_id
        FROM concept_set
      )
    )
    SELECT
      COUNT(DISTINCT CASE
        WHEN domain_id = 'Condition' THEN person_id
      END) AS condition_persons,
       
      COUNT(DISTINCT CASE
        WHEN domain_id = 'Procedure' THEN person_id
      END) AS procedure_persons,
       
      COUNT(DISTINCT CASE
        WHEN domain_id = 'Drug' THEN person_id
      END) AS drug_persons,
       
      COUNT(DISTINCT CASE
        WHEN domain_id = 'Measurement' THEN person_id
      END) AS measurement_persons,
       
      COUNT(DISTINCT CASE
        WHEN domain_id = 'Observation' THEN person_id
      END) AS observation_persons,
       
      COUNT(DISTINCT CASE
        WHEN domain_id = 'Visit' THEN person_id
      END) AS visit_persons,
      
      COUNT(DISTINCT person_id) AS overall_persons
      FROM domain_persons;
  "
  counts <- DatabaseConnector::renderTranslateQuerySql(
    connection = connection,
    sql = sql,
    concept_set_sql = SqlRender::render(conceptSetSql, vocabulary_database_schema = cdmDatabaseSchema),
    cdm_database_schema = cdmDatabaseSchema,
    snakeCaseToCamelCase = TRUE
  )
  return(counts)
}

jsonToCaprWithReference <- function(json, target) {
  expression <- CirceR::conceptSetExpressionFromJson(json)
  concepts <- c()
  excludedConcepts <- c()
  includeDescendantConcept <- c()
  includeDescendantAndExcludedConcept <- c()
  conceptIds <- c()
  conceptNames <- c()
  for (item in expression$items) {
    conceptId <- item$concept$conceptId$toString()
    conceptName <- item$concept$conceptName
    conceptIds <- c(conceptIds, conceptId)
    conceptNames <- c(conceptNames, conceptName)
    if (item$includeDescendants) {
      if (item$isExcluded) {
        includeDescendantAndExcludedConcept <- c(includeDescendantAndExcludedConcept, conceptId)
      } else {
        includeDescendantConcept <- c(includeDescendantConcept, conceptId)
      } 
    } else {
      if (item$isExcluded) {
        excludedConcepts <- c(excludedConcepts, conceptId)
      } else {
        concepts <- c(concepts, conceptId)
      }
    }
  }
  hasIncludeDescendants <- length(includeDescendantConcept) > 0 || length(includeDescendantAndExcludedConcept) > 0
  code <- paste0("cs(",
                 if (length(concepts) > 0) paste(concepts, collapse = ", ") else "",
                 if (length(concepts) > 0 && hasIncludeDescendants) ", " else "",
                 if (hasIncludeDescendants) "descendants(" else "",
                 if (length(includeDescendantConcept) > 0) paste(includeDescendantConcept, collapse = ", ") else "",
                 if (length(includeDescendantConcept) > 0 && length(includeDescendantAndExcludedConcept) > 0) ", " else "",
                 if (length(includeDescendantAndExcludedConcept) > 0) paste0("exclude(", paste(includeDescendantAndExcludedConcept, collapse = ", "), ")") else "",
                 if (hasIncludeDescendants) ")" else "",
                 if ((length(concepts) > 0 || hasIncludeDescendants) && length(excludedConcepts) > 0) ", " else "",
                 if (length(excludedConcepts) > 0) paste0("exclude(", paste(excludedConcepts, collapse = ", "), ")") else "",
                 ", name = \"", 
                 target, 
                 "\")")
  reference <- lapply(seq_along(conceptIds), 
                      function(i) list(conceptId = as.integer(conceptIds[i]),
                                       conceptName = conceptNames[i]))
  reference <- jsonlite::toJSON(reference,
                                auto_unbox  = TRUE)
  reference <- as.character(reference)
  return(tibble(capr = code, reference = reference))
}
