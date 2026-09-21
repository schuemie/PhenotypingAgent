# Use a single-context ellmer agent, equivalent to GitHub Copilot
library(ellmer)
library(dplyr)

# chat <- chat_azure_openai(
#   endpoint = keyring::key_get("genai_openai_endpoint"),
#   api_version = "2024-12-01-preview",
#   model = "o3",
#   credentials = function() keyring::key_get("genai_api_gpt4_key")
# )

chat <- Helios::chat_jnj_bedrock(
  model = "global.anthropic.claude-opus-4-8",
  api_key = keyring::key_get("genai_bedrock_key"),
  echo = "none"
)

phenotypes <- readLines("../largescalephentest/SelectedPhenotypes.txt")
definitions <- openxlsx::readWorkbook("../largescalephentest/ClinicalDefinitionLibrary564.xlsx")

# Register tools -------------------------------------------------------------------------------------------------------
options("RUN_SERVER" = FALSE)
source("tools/server.R")
chat$register_tools(list(listConceptSetsTool,
                         getConceptSetsCaprTool,
                         getCohortCountTool,
                         getDatabaseDescriptionTool,
                         countConceptSetPersonOverlapTool,
                         describeMeasurementValuesTool,
                         computeIncidenceRateTool,
                         validateCaprTool,
                         convertCaprToJsonTool,
                         generateCohortTool,
                         evaluateCohortTool,
                         samplePatientProfileTool))


# Context construction -------------------------------------------------------------------------------------------------
systemPrompt <- paste(readLines(".agents/AGENTS.md"), collapse = "\n")

constructContext <- function(phenotype, clinicalDefinition) {
  skill <- readLines(".agents/skills/cohort-developer/skill.md")
  endOfHeader <- grep("---", skill)[2]
  skill <- paste(skill[(endOfHeader + 1) : length(skill)], collapse = "\n")
  caprReference <- paste(readLines(".agents/skills/cohort-developer/CAPR_REFERENCE.md"), collapse = "\n")
  context <- paste(
    skill,
    "",
    "--- Start of CAPR_REFERENCE.md ---",
    caprReference,
    "--- End of CAPR_REFERENCE.md ---",
    "",
    sprintf("Phenotype: %s", phenotype),
    "",
    "--- Start of clinical definition ---",
    clinicalDefinition,
    "--- End of clinical definition ---",
    sep = "\n"
  )
  return(context)
}

# Run chat -------------------------------------------------------------------------------------------------------------

for (i in seq_along(phenotypes)) {
  phenotype <- phenotypes[i]
  outputFolder <- file.path("runs", sprintf("ellmer_%s", gsub("[^[:alnum:]]+", "_", phenotype)))
  if (!dir.exists(outputFolder)) {
    message("Creating cohort defintion for ", phenotype)
    dir.create(outputFolder)
    
    clinicalDefinition <- definitions |>
      filter(Phenotype == phenotype) |>
      pull(Definition)
    context <- constructContext(phenotype, clinicalDefinition)
    
    # Run chat
    chat$set_turns(list())
    chat$set_system_prompt(systemPrompt)
    response <- chat$chat(context)
    
    # Save full chat
    turns <- chat$get_turns()
    texts <- list()  
    for (t in 2:length(turns)) {
      texts[[t-1]] <- format(turns[[t]])
    }
    texts <- paste(texts, collapse = "\n\n")
    writeLines(texts, file.path(outputFolder, "chat.txt"))
    
    # Get best cohort definition
    prompt <- "
      Please return your best definition capr code.
      Output using the following structure. Do not include text outside the JSON:
      { \"capr\": \"cohort(...)\"}
    "
    bestCohortDefinition <- chat$chat_structured(prompt, type = type_object(capr = type_string()))
    json <- convertCaprToJson(bestCohortDefinition$capr)
    writeLines(json, file.path(outputFolder, "best_cohort.json"))
    
    # Save cost
    cost <- chat$get_cost("all")
    writeLines(sprintf("Total cost: $%0.2f", cost), file.path(outputFolder, "cost.txt"))
  }
}
