# Introduction to RCC for MSc in Analytics

As a student in the Master of Science in Analytics (MScA) Program, you will be able to make use of The University of Chicago’s Research Computing Center (RCC) resources in completing your capstone project.  Some courses in the program will also make use of RCC resources.

RCC provides high-end research computing resources to researchers at the University of Chicago. These resources include centrally managed high-performance computing, storage, and visualization hardware and software; scientific and technical user support; and education and training opportunities to help researchers make effective use of modern HPC technology.

Below are the basics you will need to know in order to get up and running at RCC.  For complete RCC technical documentation, see the main sections of this user guide. 

## Getting Help

RCC support staff are available to assist with technical issues (help logging in, questions about using the cluster, etc.).  Please don’t hesitate to ask questions if you encounter any technical issues.


* The preferred way of requesting support is to [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}.


* RCC’s walk-in lab is open during business hours and is located in Regenstein Library room 216. Feel free to drop by to chat with one of our staff members if you get stuck.

## Logging into Midway

For the most complete documentation regarding connecting to RCC resources, see [Connecting to Midway](../connection/main.md).

## Using Midway

See [Running Jobs on Midway](../slurm/main.md) for detailed documentation on how to run your own programs on the cluster once you've connected. 

## Software

Many commonly used software packages and libraries have been installed on Midway for your use.  For an overview of how to use software modules on Midway, consult the RCC [Software](../software/index.md) documentation page.

## SAS

SAS Studio is available to MScA students. SAS Studio is a web application
front end to SAS. To access SAS Studio, visit this link and log in with your
CNetID and password:

[https://sas-studio.rcc.uchicago.edu](https://sas-studio.rcc.uchicago.edu){:target='_blank'}

Also, an instance of SAS Enterprise Miner is available to MScA students.  To access SAS Enterprise Miner, you can visit this link:

[https://sas-miner.rcc.uchicago.edu:8343/SASEnterpriseMinerJWS/Status](https://sas-miner.rcc.uchicago.edu:8343/SASEnterpriseMinerJWS/Status){:target='_blank'}

SAS software is also available on Midway.  To load the SAS software module, use the command `module load sas`. It is recommended to use [ThinLinc](../connection/thinlinc/main.md) to log in to Midway if you want to use SAS in this manner.


## Nielsen Data

The MScA program has obtained a subset of the Nielsen Homescan data for use in teaching and research projects.  Access to this data is controlled by MScA administration.  If you require access to this data, please consult your instructor or the MScA director and request that you be approved for access to the data.

Once your user account has been approved for access to the Nielsen data, you will be able to access the data in the directory `/project/msca/data/nielsen/` on Midway.

