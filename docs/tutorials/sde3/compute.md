# Running jobs on SDE3

 SDE3 use the SLURM scheduler to allocate jobs to compute nodes. However, SDE3 has no SUs allocation requirement. 
<br><br/>
Upon connecting to SDE3, users land on a login node, which can be used for compiling and debugging code, visualizing data, editing and managing files. All intensive computations should be submitted to compute nodes. Running jobs on SDE3 is no different from [running jobs on Midway](../../slurm/main.md).

# Slurm Partitions

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


## SDE3 Shared Partitions
All SDE3 users can submit jobs to any of the following shared partitions:

=== "SDE3"
      | Partition | Nodes  | CPUs | CPU Type  | Total Memory| Local Scratch 
      | --------- | -------| -----| --------- | ------------| ------------ |
      | skylake   |   4    |  40  | gold-6148 |  96 GB      |     900 MB   | 
      | caslake-bigmem| 1  |  40  | gold-6248 | 1536 GB     |     900 MB   | 



## SDE3 Institutional Partitions
If you are a SDE3 researcher affiliated with the Booth School of Business, you are entitled to Booth purchased hardware resources. Each node has 1.8 GB of local scratch.

=== "SDE3"
      | Partition | Nodes  | Cores/nodes | CPU Type  | GPUs | GPU Type| Total Memory| Local Scratch | Nodelist     |
      | --------- | -------| ------------| --------- | ---- | ------- | ----------- | ------------- | ------------ |
      | booth     |   1    |  40         | gold-6248 | None |  None   |    1536 GB  |  1.8 GB       | sde006       | 
      | booth     |   2    |  48         | gold-6248r| None |  None   |    384 GB   |  1.8 GB       | sde[007-008] |
      | booth     |   1    |  48         | gold-6248r| 2    |  v100   |    384 GB   |  1.8 GB       | sde009       |

## SDE3 QOC

===+ "SDE3 QOS"

    | QOS     | Partitions | Max Wall Time | Max Sub Job / User |
    |---------|----------- |---------------|--------------------|
    | normal  | skylake, caslake-bigmem | 36 H          | 350                |
    | long    | skylake, caslake-bigmem, booth | 7 Days        | 200                |



To see a full list of QOS run the following
```
sacctmgr list qos format=Name,MaxWall,MaxSubmitPU
```
!!! note
    QOS for private and institutional partitions can be changed upon owner's request.

## Private Partitions
Private SDE3 partitions are typically associated with a research group with access approved by PI. Private partitions can be purchased via [RCC Cluster Partnership Program](https://rcc.uchicago.edu/support-and-services/cluster-partnership-program){:target="_blank"} to better accommodate the needs of a research group. PI may request to change QOS of private partitions at any time.



## Do I Have Access to a Partition?
To check if you have access to a partition, first determine which groups your account belongs to: 
```
groups
```
and then check AllowAccounts field in the partition summary: 
```
scontrol show partition <partition_name>
```
If AllowAccount is set to All then it is a shared partition available to all users. Otherwise, it is an institutional or private partition and one of your groups must match the AllowAccounts field in order to submit SLURM jobs to that partition. 