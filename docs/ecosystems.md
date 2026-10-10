# Overview of RCC's HPC Systems

The University of Chicago Research Computing Center (RCC) hosts a diverse range of professionally managed high-performance computing clusters, forming the backbone of the RCC's advanced computational infrastructure. RCC manages two ecosystem of HPC systems. Regular research data is hosted within the Midway ecosystem, while sensitive or regulated research data is hosted within the Secure Data Enclave (SDE) ecosystem.

## Midway Ecosystem

### [Midway3](https://rcc.uchicago.edu/midway3)

In 2021, Midway3 and Midway3-AMD were introduced as flagship clusters for multi-purpose scientific computing. It is recommended that new users opt for Midway3 due to its latest hardware and software modules. Midway3 comes with shared and private compute nodes.

### [SHARED](https://shared.rcc.uchicago.edu/)
SHARED is a storage platform for Secure Hub for Access, Reliability, and Exchange of Data. Designed as a cornerstone of UChicago's data lifecycle strategy, from collection and analysis to publication and archiving, SHARED will integrate with the University’s institutional repository, Knowledge@UChicago, and connect to national research networks like the Open Science Grid (OSG). The SHARED project and platform is led by the University of Chicago Library and Research Computing Center (RCC), with contributions from University IT Services, Data Science Institute, and Physical Sciences Division. It will provide critical [storage capacity](https://dl.acm.org/doi/10.1145/3708035.3736042) for research and supporting data science curricula development and education.

### [Beagle3](https://beag3.rcc.uchicago.edu/)

Funded by an NIH grant, Beagle3, part of Midway3 ecosystems, supports biomedical research with cutting-edge HPC resources, specializing in modeling and large-scale simulations of molecular structures. Launched in February 2022, Beagle3 features 44 compute nodes with Intel CPUs and NVIDIA GPUs. Eligibility applies.

### [MidwaySSD](https://midwayssd.rcc.uchicago.edu/)
MidwaySSD, part of the Midway3 ecosystem, serves computationally intensive Social Science Division research and educational purposes. Eligibility applies.

### [Skyway](https://cloud-skyway.rcc.uchicago.edu/)

Skyway allows users to seamlessly burst computing workloads through Midway 2 and 3 ecosystems to remote commercial cloud platforms like Amazon Web Services (AWS) and Google Cloud: Cloud Computing Services (GCP). It simplifies cloud computing tasks without requiring users to manage cloud resources. 

### [Midway2](https://rcc.uchicago.edu/support-and-services/midway2) 

Midway2, succeeding the original Midway in 2016, boasts advanced features. Midway2 comes with shared and private compute nodes. 

### [DaLI](https://dali.uchicago.edu/using-dali/)

DaLI, the Data Lifecycle Instrument, as a part of the Midway2 ecosystem, facilitates data management and sharing, offering a unified workflow for acquiring, transferring, processing, and storing experimental and observational data. It enhances data lifecycle management, sharing, and publication, supporting outreach and education. Eligibility applies.

### [GM4](https://gm4.rcc.uchicago.edu/)
GM4, a GPU-enabled cluster, is part of the Midway2 ecosystem and facilitates multiscale materials modeling and machine learning, supporting diverse molecular dynamics and continuum simulations. Funded by the NSF under the MRI program, GM4 promotes collaborative efforts in algorithm and software development. Eligibility applies.

## SDE Ecosystem
### [SDE3](https://sde-midwayr.rcc.uchicago.edu/)
SDE3 is a trusted HPC environment for research on regulated data. While the workflows on SDE3 are largely similar to those of a general-purpose HPC environment, additional controls are in place to strengthen data security and privacy, as described in the [SDE3 User Guide](tutorials/sde3/overview.md).

### SDE2
SDE2 is a trusted HPC environment for research on regulated data compliant with NIST SP800-53. While the workflows on SDE2 are largely similar to those of a general-purpose HPC environment, additional controls are in place to strengthen data security and privacy, as described in the [SDE2 User Guide](tutorials/sde2/overview.md).