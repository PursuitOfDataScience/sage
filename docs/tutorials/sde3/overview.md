# Welcome to the SDE3 User Guide

SDE3 is the RCC's secure HPC cluster that provides a trusted research environment to support work with regulated research data that requires high-level protection. 

Examples of regulated research data include:

* Personally Identifiable Information (PII)
* Limited data sets as per Health Insurance Portability and Accountability Act (HIPAA) definition
* Some types of health information 
* Data covered under the Federal Information Security Management Act (FISMA)
* Data covered under the Family Educational Rights and Privacy Act (FERPA)
* Data with security requirements set by the Institutional Review Board (IRB)
* Commercial data with security requirements set by the Data Use Agreement (DUA)

The [research data classification](https://srds.uchicago.edu/secure-research-data-usage-guide/) is provided by University Research Administration. If you have any questions about SDE3, please email [midwayr-help@rcc.uchicago.edu](mailto:midwayr-help@rcc.uchicago.edu).

## Eligibility

To use SDE3 resources, you will need to have an SDE3 user account. Although both Midway and SDE3 use CNetID for authentication, they do not share accounts. If you do not have an SDE3 user account, please see the <a href="https://sde-midwayr.rcc.uchicago.edu/getting-started/" target="_blank">Getting Started</a> section for how to apply for an account.

!!! note
    General users can apply only after the PI has been approved for an SDE3 account. Only authorized users listed in the Data Use Agreement (DUA) and/or Institutional Review Board (IRB) protocol can get access to a project hosted on SDE3 upon PI approval. If the list of authorized users is not set explicitly in the data use agreement, then any UChicago researcher approved by the PI can work with the project data hosted on SDE3.
 

Please also note that you must have enabled 
<a href="https://cnet.uchicago.edu/2FA/" target="_blank">Two Factor Authentication</a>
for your CNetID before connecting to SDE3.

## System Overview

SDE3 consists of two login nodes and four compute nodes. The total installed storage on SDE3 is 441 TB. It uses Slurm as its workload manager and the software environment module system to manage installed software.
<br><br/>
**Login Nodes:** SDE3 hosts login nodes with the following specifications: 

* CPUs: 2x Intel Xeon Gold 6130 2.1GHz
* Total cores per node: 16 cores
* Threads per core: 2
* Memory: 96GB of RAM

**Compute Nodes:** 
There are no limits on SU usage at the moment. PIs don't need to apply for an SU allocation.

**Network:**

* Intel Ethernet Controller 10Gbps Adapter
* Mellanox EDR InfiniBand with up to 100 Gbps bandwidth and sub-microsecond latency
* Neither compute nor login nodes have direct access to the Internet

**File Systems:**

* SDE3 utilizes a GPFS filesystem, with `/home` and `/project` directories mounted for private and collaborative work. 
The `/home/<CNetID>` directory has a strict quota of 30 GB, and the quota for `/project/pi-<PI_CNETID>-<ProjectName>` varies depending on the project with the default startup storage allocation of 500 GB. SDE3 does not have a scratch filesystem.


**Using SDE3:**

* SDE3 nodes run CentOS 7. Its job scheduler is [Slurm](https://slurm.schedmd.com/). Slurm commands enable you to submit, manage, monitor, and control your jobs.

**Software:**

* Organized in [modules](http://modules.sourceforge.net/)
* Use `module avail` to see what is available
* To load a particular available package, for example, `gcc` version 8.2.0, do `module load gcc/8.2.0`
* If you do not specify a version of the package, the default one is loaded
* To see what environment variables are modified when `gcc/8.2.0` is loaded, do `module show gcc/8.2.0`
* To unload `gcc/8.2.0`, do `module unload gcc/8.2.0`



