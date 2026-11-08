# Full FHIR Testing Guide

## What is Full FHIR Testing Guide?

This is a guide for those with FHIR servers to integrate the FHIR protocol
with DICOM Mock. It was originally created to test our GoSmart Graphite
GraphRAG DICOM Server.

## Before You Begin

This requires a GoSmart.Health Professional subscription. Consulting clients
also gets 1 year of professional access in the year there is a consulting
agreement.

## Prerequisites

All our products will work under Windows, Mac, and Linux.

- Python 3.12 or later with `uv`
- GoSmart.Health Professional subscription
- GoSmart FHIR Plug-In (gosmart-fhir-py-plugin)
- DICOM Mock server (dicom-py-mock-server)
- FHIR server: HAPI FHIR, FHIR Sandbox from Redox or your test FHIR server
  instance that supports SMART on FHIR JWK oAuth2.
- GoSmart Graphite GraphRAG DICOM Server (optional)
- Docker Desktop or Docker Server (X86 architecture support required)

## How It Works

1. The Mock server wakes up periodically and requests ImagingService 
   and associated Patient resource. It pools a configured amount of entries 
   (FHIR bundles) and extracts the ImagingStudy resources matching the 
   imaging modalities the Mock server supports. By default, they are, CT, UR, 
   and DR for which there are modality template files.

   Note: The entries are cached because not all of the entries many not be 
   consumed in each cycle. If the cache is exhausted it will request another 
   batch of entries until there is no more based on the "paging" _offset.

2. The FHIR Plug-In generates Modality Worklist (MWL) based on the FHIR bundlee

3. If automatic push is enabled, the FHIR Plug-In will push the generated 
   modality images to the PACS server. Alternately, a DICOM Image Viewer or 
   a PACS server can issue C-FIND and C-MOVE/C-GET operations to pull the 
   images.

4. The PACS server can then access the FHIR plug-in's FHIR proxy to retrieve 
   the the full FHIR bundles like Encounter, DiagnosticReport, etc., for 
   further processing. For example GoSmart.Health Graphite server generates 
   the GraphRAG for natural language queries for Diagnostic Report etc.

## Configurations

Most configurations are done through environment variables and we recommend
the use of `.env` to store them.

### FHIR Plug-In

GoSmart.Health will provide you with the GoSmart FHIR Plug-In as a docker
image with docker-compose.yaml

The following environment variables are required:

---

| Variable                        | Description                                                         |
|:--------------------------------|:--------------------------------------------------------------------|
| `GOSMART_FHIR_CLIENT_ID`        | FHIR (EPIC, Redox, etc.) Backend Services Client ID                 |
| `GOSMART_FHIR_JWKS_URL`         | Public JWKS endpoint URL                                            |
| `GOSMART_FHIR_JWKS_PRIVATE_KEY` | Path to RSA private key PEM file                                    |
| `GOSMART_FHIR_JWKS_KID`         | Key ID registered in JWKS                                           |
| `GOSMART_FHIR_JWKS_ALG`         | Signing algorithmv (RS384, RS512, ES384, or ES512)                  |
| `GOSMART_FHIR_TOKEN_URL`        | Epic OAuth2 token endpoint (set to `"None"` for HAPI FHIR w/o auth) |
| `GOSMART_FHIR_BASE_URL`         | FHIR R4 base URL                                                    |

----
### Example Configurations

You can place these environment variables in a `.env` file in the root directory of your project
or in `docker-compose.yaml` file.

#### EPIC Sandbox

```shell
GOSMART_FHIR_CLIENT_ID=bf123456-789a-bcde-f01234567890abcde
GOSMART_FHIR_JWKS_URL=https://my.example.com/.well-known/jwks.json
GOSMART_FHIR_JWKS_PRIVATE_KEY=/Users/myhome/my-private.pem
GOSMART_FHIR_JWKS_KID=my-kid-0001
GOSMART_FHIR_JWKS_ALG=RS384
#
GOSMART_FHIR_TOKEN_URL=https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token
GOSMART_FHIR_BASE_URL=https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/
```

#### REDOX Sandbox

```shell
GOSMART_FHIR_CLIENT_ID=bf123456-789a-bcde-f01234567890abcde
GOSMART_FHIR_JWKS_URL=https://gosmart.health/.well-known/jwks.json
GOSMART_FHIR_JWKS_PRIVATE_KEY=/Users/myhome/my-private.pem
GOSMART_FHIR_JWKS_KID=my-kid-0001
GOSMART_FHIR_JWKS_ALG=RS384

GOSMART_FHIR_TOKEN_URL=https://api.redoxengine.com/v2/auth/token
GOSMART_FHIR_BASE_URL=https://api.redoxengine.com/fhir/R4/redox-fhir-sandbox/Development
```

#### HAPI FHIR (no access token)

```shell
# ----- HAPI FHIR ---------------------------
GOSMART_FHIR_TOKEN_URL=none
GOSMART_FHIR_BASE_URL=http://localhost:8087/fhir
#
```

### Mock Server Configurations

- GOSMART_MS_WML_GENERATOR_MODE: Set this to `fhir` mode.
- GOSMART_MS_FHIR_PLUGIN_URL: URL of the FHIR Plugin API root usually http://localhost:8088.
- GOSMART_MS_FHIR_PATIENT_COUNT: Number of patient FHIR ImagingStudy bundles to pull per 
  iteration.
- GOSMART_MS_FHIR_PATIENT_ID_SYSTEM: System used for generating patient IDs.
- GOSMART_MS_TRANSFER_SYNTAX: Transfer syntax to use for generated images.
- GOSMART_MS_MIN_SLICES: Minimum number of slices to generate for each image.
- GOSMART_MS_MAX_SLICES: Maximum number of slices to generate for each image.
- GOSMART_MS_STRESS: Enable stress testing mode.
- GOSMART_MS_SCP_PORT: Port number for the Mock Server's SCP (Storage Commitment Point).

- GOSMART_MS_AUTO_PUSH_AE: The destination AE Title. Empty will disable the 
  feature
- GOSMART_MS_AUTO_PUSH_HOST: The destination host. Empty will disable the 
  feature
- GOSMART_MS_AUTO_PUSH_PORT: The destination port. Empty will disable the 
  feature
- GOSMART_MS_AUTO_PUSH_SEC: The delay in seconds between each push. Empty or 
  0 (zero) will disable the feature

GOSMART_MS_AUTO_PUSH_AE=GO_GRAPHITE
GOSMART_MS_AUTO_PUSH_HOST=localhost
GOSMART_MS_AUTO_PUSH_PORT=11112
GOSMART_MS_AUTO_PUSH_SEC=60

```shell
GOSMART_MS_WML_GENERATOR_MODE=fhir
GOSMART_MS_FHIR_PLUGIN_URL=http://localhost:8088
GOSMART_MS_FHIR_PATIENT_COUNT=200
# This URN refers to Massachusetts Drivers Licence number in Synthea
# short string that looks like a hospital MRN.
# Use any other you feel is right.
GOSMART_MS_FHIR_PATIENT_ID_SYSTEM="urn:oid:2.16.840.1.113883.4.3.25"
GOSMART_MS_TRANSFER_SYNTAX=JPEG2000_LOSSLESS
GOSMART_MS_MIN_SLICES=96
GOSMART_MS_MAX_SLICES=128
GOSMART_MS_STRESS=false
GOSMART_MS_SCP_PORT=11114
# Automatic Push Configurations
GOSMART_MS_AUTO_PUSH_AE=GOGRAPHITE
GOSMART_MS_AUTO_PUSH_HOST=127.0.0.1
GOSMART_MS_AUTO_PUSH_PORT=11112
GOSMART_MS_AUTO_PUSH_SEC=60

```

## Generate FHIR with Synthea and Load to Your FHIR

I will be using the Synthea and HAPI FHIR server as an example. If you have
specific requirements, we can engage in helping you set up FHIR test exams.

CAUTION: HAPI FHIR ingestion process takes a very long time. Ingesting  
1000 patient bundles will take upwards of 30 min or more. Limit to a few 
hundred patients at a time.

CAUTION 2: ImagingStudy Dates are not be current or recent if you use 
all the defaults. The dates will reflect in the generated DICOM objects.

1. Use the synthea CLI to generate a FHIR JSON bundle.
2. Using a Rest script like curl, POST the bundle to the HAPI FHIR server at 
   the FHIR endpoint.

## Start the Services

### Start the GoSmart FHIR Plug-In API

Inspect and run `gosmart-fhir-py-plugin/start-api.sh`
 
If you also need the MCP Service:

Inspect and run `gosmart-fhir-py-plugin/start-api.sh`

### Start the Mock Server. 

Inspect and run `gosmart-fhir-py-plugin/start.sh`
