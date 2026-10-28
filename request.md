# Goal

Generate DICOM Modality Worklist (MWL) Entries (also C-FIND entries driven from the MWL entries) from the ImagingStudy
resources available via the FHIR queries on a HAPI FHIR Server.

**Note** that this will not normally work with commercial FHIR server like EPIC. However, in production, the new patient  and studies enters our Graph PACS via the real MWL, HL7 ORM, or
DICOM C-STORE of acquired images. The goal on this is to create the MWL synthetically but driven from the data in the HAPI FHIR server.

We will load HAPI FHIR Syntha generated patients and their histories. Using the histories starting with the `ImagingStudy` resource, we can auto-generate patient, study, series, and instances in the Mock Database instead of using the internal synthesizer, as an alternative.

## Design

- This is a Professional feature that require our `gosmart-fhir-py-plugin` server.
- The FHIR server publises the `patient-imaging` API:

```
@router.get("/patient-imaging")
async def get_imaging_study_endpoint(
    modalities: list[str] = Query(default=["CT", "US", "DR"]),  # noqa: B008
    raw_count: int = Query(default=200, ge=1, le=1000),
    raw_offset: int = Query(default=0, ge=0),
)
```

### New Environment Variables Introduced

| Environment Variable | Supported Aliases | Default | Description |
| :--- | :--- | :--- | :--- |
| `GOSMART_MS_FHIR_PLUGIN_URL`| `FHIR_PLUGIN_URL` | `http://localhost:8088` | FHIR Plugin Module URL. Always local. |
| `GOSMART_MS_WML_GENERATOR_MODE` | `GENERATOR_MODE` | `internal` | Study generator mode `internal`, `fhir`, or empty, 'interna' as default |

### Existing Environment Variables Utilized

| Environment Variable | Supported Aliases | Default | Description |
| :--- | :--- | :--- | :--- |
| `GOSMART_MS_MWL_WINDOW_HR` | `MWL_WINDOW_HR` | `24` | Retention window in hours for active Modality Worklist (MWL) entries. |
| `GOSMART_MS_MWL_RATE_PER_HR` | `MWL_RATE_PER_HR` | `12.0` | Base MWL creation rate per hour during business hours (9 AM - 5 PM local; 5% rate off-hours). |
| `GOSMART_MS_AUTO_PUSH_AE` | `AUTO_PUSH_AE` | `""` | Destination Application Entity (AE) title to push to (default empty string, disabled). |
| `GOSMART_MS_AUTO_PUSH_HOST` | `AUTO_PUSH_HOST` | `127.0.0.1` | Destination host / IP address for auto-push C-STORE delivery. |
| `GOSMART_MS_AUTO_PUSH_PORT` | `AUTO_PUSH_PORT` | `11113` | Destination TCP port for auto-push C-STORE delivery. |
| `GOSMART_MS_AUTO_PUSH_SEC` | `AUTO_PUSH_SEC` | `0` | Number of seconds interval between auto-pushes (default 0, disabled). |

## FHIR Mode Description

### Configuration

- `GOSMART_MS_FHIR_PLUGIN_URL` has a valid accessible URL.
- `GOSMART_MS_WML_GENERATOR_MODE` should be set to `fhir`
- When above configuration is valid then the following will occur.

### Behavior

## Call `/api/v1/patient-imaging`

It accepts `raw_count` and `row_offset` and also returns these values for paging through. Create those local values for the application life-time.

We will use the same `wake_up` timer configured with `GOSMART_MS_MWL_RATE_PER_HR`, and if `GOSMART_MS_WML_GENERATOR_MODE` holds the value `fhir` then it will operate to generate the MWL entries only from
the FHIR values.

### Parse the Returned FHIR Bundles

The call to `/api/v1/patient-imaging` will provide the following DTO structure.

#### The DTO Structure

```python

from fhir.resources.R4B.bundle import Bundle
from pydantic import BaseModel


class ImagingStudyBundleDTO(BaseModel):
    raw_offset: int = 0
    raw_count: int = 0
    imaging_study: list[Bundle] = []
```

Imaging Study FHIR bundle list `imaging_study` contains "Patient" and "ImagingStudy" resources in each bundle.
With this we should be able to form MWL entries.

If it returns an empty list we have exhausted all the records. Instead of complicating the logic, just continue to call
the API and get 0 results.

For each "wake up" iteration, pass the raw_offset back to the /api/v1/patient-imaging call.

