# DICOM Mock Server (`dicom-py-mock-server`)

Synthetic DICOM object generator, Modality Worklist (MWL) SCP, DICOM SCP (C-FIND, C-MOVE, C-STORE), DICOMweb (QIDO-RS, WADO-RS, STOW-RS), and Model Context Protocol (MCP) SSE server.

> [!WARNING]
> **NOT FOR CLINICAL USE**
> This service is strictly intended for developer test harnesses, PACS integration testing, and local network simulation. It does not provide authentication or authorization.

---

## Quickstart with Docker Compose

Create a `docker-compose.yaml` file:

```yaml
services:
  dicom-mock-server:
    image: imanabu/dicom-py-mock-server:latest
    container_name: dicom-py-mock-server
    ports:
      - "8000:8000"
      - "11112:11112"
      - "2575:2575"
    environment:
      - GOSMART_MS_HOST=0.0.0.0
      - GOSMART_MS_PORT=8000
      - GOSMART_MS_SCP_PORT=11112
      - GOSMART_MS_HL7_PORT=2575
      - GOSMART_MS_SCP_AE_TITLE=GOSMART_SCP
      - GOSMART_MS_LOG_LEVEL=INFO
      - GOSMART_MS_TRANSFER_SYNTAX=JPEG2000_LOSSLESS
    volumes:
      - ./data/dicom_storage:/app/data/dicom_storage
      - ./received:/app/received
      - ./logs:/app/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 5s
```

Run the container:

```bash
docker compose up -d
```

Check health:

```bash
curl http://localhost:8000/health
```

---

## Quickstart with Docker CLI

```bash
docker run -d \
  --name dicom-py-mock-server \
  -p 8000:8000 \
  -p 11112:11112 \
  -p 2575:2575 \
  -v $(pwd)/data/dicom_storage:/app/data/dicom_storage \
  -v $(pwd)/received:/app/received \
  -v $(pwd)/logs:/app/logs \
  imanabu/dicom-py-mock-server:latest
```

---

## Network Ports

| Port | Protocol | Description |
| :--- | :--- | :--- |
| **8000** | HTTP / TCP | FastAPI REST API, DICOMweb (QIDO-RS, WADO-RS, STOW-RS), and MCP SSE endpoint (`/sse`) |
| **11112** | DICOM / TCP | DICOM Upper Layer Service (C-ECHO, C-FIND, C-MOVE, C-STORE, MWL SCP) |
| **2575** | HL7 / MLLP | HL7 v2 ORM Order Ingestion Listener (optional) |

---

## Persistence Volumes

| Container Path | Purpose |
| :--- | :--- |
| `/app/data/dicom_storage` | Generated and C-STORE received DICOM P10 datasets |
| `/app/received` | STOW-RS received DICOM instances |
| `/app/logs` | Structured application log files |

---

## Key Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `GOSMART_MS_HOST` | `0.0.0.0` | HTTP listen host inside container |
| `GOSMART_MS_PORT` | `8000` | HTTP listen port inside container |
| `GOSMART_MS_SCP_PORT` | `11112` | DICOM SCP listen port |
| `GOSMART_MS_SCP_AE_TITLE` | `GOSMART_SCP` | DICOM Application Entity Title |
| `GOSMART_MS_TRANSFER_SYNTAX` | `JPEG2000_LOSSLESS` | Target transfer syntax (`RAW`, `JPEG`, `JPEG2000_LOSSLESS`, `RLE`) |
| `GOSMART_MS_MIN_SLICES` | `8` | Minimum slices for volume generation |
| `GOSMART_MS_MAX_SLICES` | `24` | Maximum slices for volume generation |
| `GOSMART_MS_MWL_RATE_PER_HR` | `12.0` | Automated MWL generation rate per business hour |
| `GOSMART_MS_LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Project Repository

Source code and documentation: [gosmart-health/dicom-py-mock-server](https://github.com/gosmart-health/dicom-py-mock-server)

