# Jupyter Notebooks for DICOM Mock Server

This directory contains interactive Jupyter notebooks for exploring, testing, and integrating with `dicom-py-mock-server`.

---

## Prerequisites

Start the mock server locally before executing notebook cells:

```bash
# Option 1: Run natively with start script
./start.sh

# Option 2: Run via Docker Compose
docker compose up
```

By default, the server exposes:
- **Port 8000**: REST API, DICOMweb services (QIDO-RS, WADO-RS, WADO-URI, STOW-RS), and MCP SSE.
- **Port 11112**: DICOM SCP AE (`MOCK_SCP`) supporting C-ECHO, C-FIND, C-MOVE, C-STORE, and Modality Worklist (MWL).
- **Port 2575**: HL7 v2 MLLP order ingestion listener.

---

## Launching Jupyter with `uv`

You can run Jupyter Lab or Notebook on-demand using Astral `uv` without polluting your global Python environment or permanently adding heavy notebook dependencies to the core project:

```bash
# Launch JupyterLab pointing to the notebooks folder
uv run --with jupyterlab jupyter lab notebooks/

# Or launch classic Jupyter Notebook
uv run --with notebook jupyter notebook notebooks/
```

If you prefer installing Jupyter into your active virtual environment:
```bash
uv pip install jupyterlab
jupyter lab notebooks/
```

---

## Available Notebooks

| Notebook | Description |
| :--- | :--- |
| [`01_dicom_mock_server_quickstart.ipynb`](01_dicom_mock_server_quickstart.ipynb) | Interactive walkthrough covering REST status checks, MWL worklist creation, DICOMweb QIDO-RS searches, WADO-RS image retrieval, and DIMSE C-ECHO verification. |

---

## Key Libraries Used in Notebooks

The project's virtual environment already includes core medical imaging libraries:
- [`pydicom`](https://pydicom.github.io/): DICOM Part 10 dataset parsing, inspection, and manipulation.
- [`pynetdicom`](https://pydicom.github.io/pynetdicom/): DIMSE network protocol communications (C-ECHO, C-FIND, C-MOVE, C-STORE).
- [`httpx`](https://www.python-httpx.org/) / `urllib`: REST API and DICOMweb HTTP client calls.
- [`Pillow`](https://python-pillow.org/) & `numpy`: Image and frame visualization.

