# Phenotyping Agent

Here you'll find a (very) experimental phenotyping agent. 
It is currently intended to be run using Github Copilot inside Visual Studio.

It has lots of dependencies you probably don't have:

- Access to a database server with patient-level data in the OMOP Common Data Model
- Access to tables containing a `KEEPER` Reference Cohort with a custom table for the patient profiles of the reference cohort.
- Access to LLMs to run `Phenelope`.
- Development version of `Phenelope` (i.e. a version that does not require providing the initial concept ID).

It also uses pre-computed concept sets.

Right now the only pre-computed data is for Acute Liver Failure.

# Example

The current example used for development:

```text
/cohort-developer #file:acute liver failure.txt 
```
