# Welcome to the SDE2 User Guide

SDE2 is an HPC cluster designed to support research involving restricted data classified at the [moderate-impact](https://srds.uchicago.edu/secure-research-data-usage-guide/) level. Like other HPC systems managed by RCC, SDE2 allows users to process large amounts of data using distributed computing managed by the Slurm job scheduler. Research data subject to a Data Use Agreement, Institutional Review Board (IRB) protocol, or a procurement contract is considered restricted data. For common examples of sensitive data categories, refer to the [Secure Research Data Strategy](https://srds.uchicago.edu/secure-research-data-usage-guide).

If you have any questions about SDE2, please email midwayr-help@rcc.uchicago.edu.

## Eligibility

All UChicago researchers with PI status are eligible to establish workspaces on SDE2. However, the project must be subject to an active Data Use Agreement (DUA) and/or an approved Institutional Review Board (IRB) protocol, and/or an executed Procurement Contract (PC). Additionally, the data must not exceed the moderate-impact level. High-impact data should not be stored on SDE2 — RCC offers a dedicated SDE3 system for high-impact data. Public or non-sensitive data can be stored on any of the general-purpose HPC systems managed by RCC within the Midway ecosystem.


## Access and Allocation
Allocation on SDE2 is provided for the duration of the project and revoked upon project completion or expiration of the associated data governing agreements. A workspace is requested by the PI for each project. Unlike the Midway ecosystem, where a single account grants access to all of a PI's projects, on SDE2 users must be authorized separately for each project. A user account for the Midway ecosystem (Midway2, Midway3, etc.) does not apply to SDE2 — a separate user account is required. Please also note that you must have enabled [Two Factor Authentication](https://cnet.uchicago.edu/2FA) for your CNetID before connecting to SDE2.

!!! note
    Researchers can apply for general user accounts only after a PI has established a project workspace on SDE2. Please reach out to your PI to find the project acronym when requesting a user account.
 
## System Overview

SDE2 consists of multiple login nodes and a collection of compute nodes. A shared filesystem supports up to 750 TB of data. Every PI receives 500 GB of storage at no charge. Additional storage can be purchased through the Cluster Partnership Program; please email cpp@rcc.uchicago.edu with the system name and desired storage size.
<br><br>

**File System:**

* SDE2 uses a GPFS filesystem with `/home` and `/project` directories for private and collaborative work, respectively. The `/home/<CNetID>` directory has a strict quota of 30 GB, and the `/project/pi-<PI_CNETID>-<ProjectName>` directory quota varies by project. SDE2 does not have a scratch filesystem.


**Software:**

RCC maintains centrally-supported scientific software on SDE2 and can install additional packages on request. Users can also install their own project-specific software. However, due to security and privacy controls, the installation process may involve extra steps — please contact us at midwayr-help@rcc.uchicago.edu if you have any questions.

Freely available scientific software is shared with all users at no cost. Proprietary software may have limited availability due to license count restrictions or licenses tied to a particular research group. Please reach out if you would like to request installation of proprietary software.

* Use `module avail` to see what is available
* To load a particular available package, for example, `gcc` version 8.2.0, run `module load gcc/8.2.0`
* If you do not specify a version, the default version is loaded
* To see which environment variables are modified when `gcc/8.2.0` is loaded, run `module show gcc/8.2.0`
* To unload `gcc/8.2.0`, run `module unload gcc/8.2.0`
