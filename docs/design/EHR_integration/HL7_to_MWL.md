# HL7 Order Message (ORM) to DICOM Modality Worklist Mapping (MWL)

The mapping from HL7 v2 `ORM^O01` (or `OMG^O19` / `OMI^O23` in v2.5+) messages to DICOM Modality Worklist (MWL) information modules, aligned with the **IHE Radiology Scheduled Workflow (SWF)** profile:

| DICOM Information Entity / Module | DICOM Tag & Description | Primary HL7 v2 Field & Component |
| --- | --- | --- |
| **Patient Identification** | `(0010,0010)` Patient's Name | `PID-5` (Patient Name: `Family^Given^Middle^Prefix^Suffix`) |
|  | `(0010,0020)` Patient ID | `PID-3.1` (ID Number / MRN) |
|  | `(0010,0021)` Issuer of Patient ID | `PID-3.4` (Assigning Authority / Namespace ID) |
| **Patient Demographic** | `(0010,0030)` Patient's Birth Date | `PID-7` (Date/Time of Birth $\rightarrow$ extract `YYYYMMDD`) |
|  | `(0010,0040)` Patient's Sex | `PID-8` (Administrative Sex: `M` $\rightarrow$ `M`, `F` $\rightarrow$ `F`, `O` $\rightarrow$ `O`) |
|  | `(0010,1030)` Patient's Weight | `OBX` segment or `PV1-...` (or `PID-...` depending on local schema) |
|  | `(0010,2160)` Ethnic Group | `PID-10` (Race) / `PID-22` (Ethnic Group) |
| **Patient Medical** | `(0010,2000)` Medical Alerts | `AL1-3` (Allergen Code/Mnemonic/Description) |
|  | `(0010,21C0)` Pregnancy Status | `OBX` segment where `OBX-3` = LOINC for pregnancy status |
|  | `(0038,0050)` Special Needs | `OBR-12` (Danger Code) or `PV1-16` (VIP Indicator) |
| **Visit Identification / Status** | `(0038,0010)` Admission ID (Visit Number) | `PV1-19` (Visit Number) |
|  | `(0038,0300)` Current Patient Location | `PV1-3` (Assigned Patient Location: `PointOfCare^Room^Bed`) |
| **Order Identification** | `(0008,0050)` Accession Number | `OBR-18` (Placer Field 1) or `ORC-25` / `OBR-20` (Filler Field 1) |
|  | `(0040,1001)` Requested Procedure ID | `OBR-19` (Placer Field 2) or `OBR-20` (Filler Field 2) |
|  | `(0040,1002)` Reason for the Requested Procedure | `OBR-31` (Reason for Study) or `DG1-3` (Diagnosis Description) |
|  | `(0040,1003)` Requested Procedure Priority | `TQ1-9` or `OBR-27.6` / `ORC-7.6` (`S` $\rightarrow$ `STAT`, `A` $\rightarrow$ `ASAP`, `R` $\rightarrow$ `ROUTINE`) |
| **Requested Procedure** | `(0032,1060)` Requested Procedure Description | `OBR-4.2` (Universal Service Identifier - Text) |
|  | `(0032,1064)` Requested Procedure Code Sequence | `OBR-4.1` (Identifier) & `OBR-4.3` (Coding System) |
|  | `(0008,0090)` Referring Physician's Name | `PV1-8` or `OBR-10` (Collector Identifier / Ordering Provider) |
| **Scheduled Procedure Step (SPS)** | `(0040,0100)` Scheduled Procedure Step Sequence | *Generated from Order/Scheduling details* |
| ↳ *inside SPS* | `(0040,0001)` Scheduled Station AE Title | Derived from scheduling configuration / `AIP-3` (Resource ID) |
| ↳ *inside SPS* | `(0040,0002)` Scheduled Procedure Step Start Date | `AIS-3` / `TQ1-7` / `OBR-27.4` (Date component: `YYYYMMDD`) |
| ↳ *inside SPS* | `(0040,0003)` Scheduled Procedure Step Start Time | `AIS-3` / `TQ1-7` / `OBR-27.4` (Time component: `HHMMSS`) |
| ↳ *inside SPS* | `(0008,0060)` Modality | `OBR-24` (Diagnostic Serv Sect ID) or mapped from `OBR-4` |
| ↳ *inside SPS* | `(0040,0007)` Scheduled Procedure Step Description | `OBR-4.2` or mapped protocol description |
| ↳ *inside SPS* | `(0040,0008)` Scheduled Protocol Code Sequence | `OBR-4.1` / mapped protocol code |
| ↳ *inside SPS* | `(0040,0009)` Scheduled Procedure Step ID | Generated unique ID (often `<FillerOrderNumber>-<StepIndex>`) |

---

**HL7 v2 Specific Nuances**

* **Accession Number Sourcing:** While IHE SWF points to `OBR-18` (Placer Field 1) or `ORC-25` (Order Status Modifier / filler assignment), most deployed hospital RIS interfaces deliver the Accession Number in either `OBR-20` (Filler Field 1) or `OBR-18`. Modality worklist servers must be configured to accommodate whichever segment the departmental RIS uses.
* **Order Control Codes (`ORC-1`):**
* `NW` (New Order) or `SN` (Send Order Number) triggers creation of the MWL item.
* `CA` (Cancel Request), `OC` (Order Canceled), or `DC` (Discontinue) removes or marks the item as discontinued/canceled on the worklist.
* `XO` (Change Order) updates the existing SPS records matching the Accession Number / Placer-Filler pair.


* **Timing & Quantity (`OBR-27` vs. `TQ1`):** In HL7 v2.3/v2.4 messages, appointment start dates and priorities reside in the composite field `OBR-27`. In HL7 v2.5 and later (`OMG^O19` / `OMI^O23`), this is formally deprecated in favor of explicit `TQ1` (Timing/Quantity) and `TQ2` segments.