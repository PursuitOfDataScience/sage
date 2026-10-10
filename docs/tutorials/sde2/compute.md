# Running jobs on SDE2

SDE2 uses the Slurm scheduler to allocate jobs to compute nodes. Unlike other RCC systems, SDE2 does not require a Service Units (SUs) allocation.
<br><br>
Upon connecting to SDE2, users land on a login node, which can be used for compiling and debugging code, visualizing data, and editing and managing files. All intensive computations should be submitted to compute nodes. Running jobs on SDE2 is no different from [running jobs on Midway](../../slurm/main.md).

## Slurm Partitions

Partitions are collections of compute nodes with similar characteristics. Normally, a user submits a job to a partition (via Slurm flag `--partition=<partition>`) and then the job is allocated to any idle compute node within that partition. To get a full list of available partitions, type the following command in the terminal
```
sinfo -o "%20P %5D %14F %4c %8G %8z %26f %N"
```
The typical output will include: 

| <div style="width:220px">Column</div> | Description                                                         |
|---------------------------------------|---------------------------------------------------------------------|
| `S:C:T`                               | Number of sockets, cores, and threads                               |
| `NODES(A/I/O/T)`                      | Number of nodes by state in the format "allocated/idle/other/total" |
| `AVAIL_FEATURES`                      | Available features such as CPUs, GPUs, internode interfaces         |
| `NODELIST`                            | Compute nodes IDs within the given partition                        |

If a user wants to submit their job to the particular compute node, this can be requested by adding the Slurm flag `--nodelist=<compute_node_ID>`. Compute nodes that differ in available features can be allocated by setting an additional constraint `--constraint=<compute_node_feature>`, for example `--constraint=v100` will allocate job to the compute node with NVIDIA V100 GPUs.


## Shared Partitions
The following partitions are shared among all users:

=== "SDE2"
      | Partition | Nodes  | CPUs | CPU Type  | Total Memory| Local Scratch 
      | --------- | -------| -----| --------- | ------------| ------------ |
      | caslake   |   6    |  48  | gold-6248r |  192 GB      |     884 MB   | 


## Private Partitions
If your project requires dedicated compute nodes, please contact cpp@rcc.uchicago.edu and include the system name and desired node configuration. We will work with you to determine the most suitable configuration and prepare the procurement contract.
 
        
