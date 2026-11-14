# Partitions
Midway compute nodes are organized into "partitions", collections of compute nodes with similar characteristics, such as hardware configuration or ownership. When a user submits a job to a partition (via Slurm flag `--partition=<partition>`), the job is allocated by the Slurm scheduler to any idle compute node within that partition. If a user wants to submit a job to a particular compute node, this can be requested by adding `--nodelist=<compute_node_ID>`. Most users will submit jobs to a 'shared' partition: a partition accessible to all Midway users. 

## How Do I Get a Full List of Partitions?

To get a full list of partitions available On Midway2 or Midway3, log in to the system and type in the terminal:
```
sinfo -o "%20P %5D %14F %4c %8G %8z %26f %N"
```
The typical output will include: 

| Column           | Description                                                         |
|------------------|---------------------------------------------------------------------|
| `AVAIL_FEATURES` | Available features such as CPUs, GPUs, and internode interfaces     |
| `NODELIST`       | IDs of the compute nodes within the given partition                 |
| `NODES(A/I/O/T)` | Number of nodes by state in the format "allocated/idle/other/total" |
| `S:C:T`          | Number of sockets, cores, and threads                               |

If a user wants to submit their job to the particular compute node, this can be requested by adding the Slurm flag `--nodelist=<compute_node_ID>`. Compute nodes that differ in available features can be allocated by setting an additional constraint `--constraint=<compute_node_feature>`; for example, `--constraint=v100` will allocate the job to the compute node with NVIDIA V100 GPUs. 

You can also check the state of nodes in a given partition, for example, `caslake`, by running the following command: 
```
nodestatus caslake
```

## What Partitions I Can Use?
To submit jobs to a partition, ensure that your account is accepted by the partition. Begin by determining the accounts you belong to. Then set the variable ACCOUNT to the account you would like to check (usually in the format pi-<PI_CNetID>), and then retrieve the list of partitions using:
```
groups
```

=== "Midway2"
    ```
    export ACCOUNT=<account_name>
    ```
    ```
    sacctmgr list assoc account=$ACCOUNT -n format=Partition | sort -u
    ```
===+ "Midway3, Midway-AMD, MidwaySSD, Beagle3"
    ```
    export ACCOUNT=<account_name>
    ```
    ```
    scontrol show partition | grep -B 1 -P "(?=.*AllowAccounts)(?=.*$ACCOUNT) | (?=.*AllowAccounts=ALL)" | grep Partition | sed 's/.*=//'
    ```

## Configurations
All Midway users can submit jobs to any of the shared partitions. 
Beagle3 users, in addition to shared partitions, have access to Beagle3 partitions too. 

**Parameters are shown per node**.
=== "Midway2 - Shared"

      |   Partition  | # of Nodes | # of Cores/node | CPU Type  | # of GPUs/node | GPU Type | Memory/node | <div style="width:158px">Nodelist</div> |
      |------------|-------|--------|-----------|------|----------|--------|----------|
      | `broadwl`    | 323   | 28   | e5-2680v4 | None | None     | 64 GB  | vary |
      | `broadwl-lc` | 14    | 28   | e5-2680v4 | None | None     | 64 GB  | midway2-[0203-0216] |
      | `bigmem2`    | 5     | 28   | e5-2680v4 | None | None     | 512 GB | midway2-bigmem[01-04,06]|
      | `gpu2`       | 6     | 28   | e5-2680v4 | 4    | k80      | 128 GB | midway2-gpu[01-06] |

=== "DaLI - Shared"

      |   Partition  | # of Nodes | # of Cores/node | CPU Type  | # of GPUs/node | GPU Type | Memory/node | <div style="width:158px">Nodelist</div> |
      |------------|-------|--------|-----------|------|----------|--------|----------|
      | `dali`    | 29   | 40   | gold-6148 | None | None     | 96 GB  | vary |

===+ "Midway3 - Shared"

      | Partition  | # of Nodes | # of Cores/node | CPU Type | # of GPUs/node    | GPU Type | Memory/node |<div style="width:140px">Nodelist</div>  |
      |------------|-------|-------|----------|---------|----------|--------|---------|
      | `caslake`   | 184   | 48   | gold-6248r | None  | None     | 192 GB       | vary |
      | `bigmem`    | 1     | 48   | gold-6248r | None  | None     | 768 GB       | midway3-0317|
      | `bigmem`    | 1     | 48   | gold-6248r | None  | None     | 1536 GB      | midway3-0318|
      | `amd-hm`    | 1     | 128  | epyc-7702  | None  | None     | 2048 GB      | midway3-0541|
      | `amd`       | 40    | 128  | epyc-7702  | None  | None     | 256 GB       | midway3-0[501-539,549]
      | `gpu`       | 1     | 48   | gold-6248r | 4     | a100     | 384 GB       | midway3-0294|
      | `gpu`       | 5     | 48   | gold-6248r | 4     | v100     | 192 GB       | midway3-[0277-0281] |
      | `gpu`       | 5     | 48   | gold-6248r | 4     | rtx6000  | 192 GB       | midway3-[0282-0286] |

      !!! note "GPU node Memory/node column: system RAM, not GPU VRAM"
          The Memory/node column shows physically installed **system RAM** (requestable via
          `--mem`), not GPU VRAM (accessed by requesting GPUs via `--gres=gpu:N`). For `gpu`
          partition nodes, the maximum requestable via `--mem` is also lower than the
          hardware total due to OS and SLURM overhead: **375 G** for the A100 node
          and **180 G** for V100 and RTX6000 nodes. Requesting the full hardware
          amount (384 GB / 192 GB) will cause job submission to fail.

=== "Beagle3 - Dedicated"

      | Partition | # of Nodes  | # of Cores/node | CPU Type  | # of GPUs/node | GPU Type |  Memory/node | Nodelist |
      | --------- | -------| ------| --------- | ---- | ------- | ------ | ---------|
      | `beagle3` |   22   |  32   | gold-6346 | 4    |  a100   |    256 GB   | beagle3-[0001-0022] |
      | `beagle3` |   22   |  32   | gold-6346 | 4    |  a40    |    256 GB   | beagle3-[0023-0044] |
      | `beagle3-bigmem` |   4    |  32   | gold-6346 | None |  None   |    512 GB   | beagle3-bigmem[1-4] |


=== "MidwaySSD - Dedicated"

      | Partition | # of Nodes | # of Cores/node | CPU Type   | # of GPUs/node | GPU Type | Memory/node | Storage/node | 
      |-----------|-------|------------|------------|------|----------|--------------|--------------|
      | `ssd`       | 18    | 48   | gold-6248r | None | None     | 192 GB       | 960 GB |
      | `ssd-gpu`   | 1     | 32   | gold-6346  | 4    | a100     | 256 GB       | 960 GB |


=== "KICP - Dedicated"

      | Partition | # of Nodes | # of Cores/node | CPU Type   | # of GPUs/node | GPU Type | Memory/node |
      |-----------|-------|------------|------------|------|----------|--------------|
      | `kicp`      | 6     | 48   | gold-6248r | None | None     | 192 GB       |
      | `kicp-gpu`  | 1     | 32   | gold-5218  | 4    | v100     | 192 GB       |

## <a name="shared-partition-qos"></a> Partition QoS

This table details the job limits of each partition, set via a Quality of Service (QoS) accessible via 
```
rcchelp qos
```

=== "Midway2 QoS - Shared"

    | Partition | Max Nodes/User | Max CPUs/User | Max Jobs/User | Max Wall Time |
    |-----------|--------------------|-------------------|-------------------|---------------|
    | `broadwl` | 100                | 2800              | 100               | 36 H          |
    | `gpu2`    | None               | None              | 10                | 36 H          |
    | `bigmem2` | None               | 112               | 5                 | 36 H          |


===+ "Midway3 QoS - Shared"

    | Partition | Max Nodes/User | Max CPUs/User | Max Jobs/User | Max Wall Time |
    |-----------|--------------------|-------------------|-------------------|---------------|
    | `caslake` | 100                | 4800              | 1000              | 36 H          |
    | `gpu`     | 4                  | 192               | 12                | 36 H          |
    | `bigmem`  | 96                 | 192               | 10                | 36 H          |
    | `amd`     | 64                 | 128               | 200               | 36 H          |


=== "Beagle3 QoS - Dedicated"
    | Partition | Max Nodes/User | Max CPUs/User | Max Jobs/User | Max Wall Time |
    |-----------|----------------|---------------|-------------------|---------------|
    | `beagle3` | 8            | 256           | 12                | 48 H          |
    | `beagle3-long`| 8       | 128           | 12                | 96 H          |
    | `beagle3-bigmem`| 2     | 64            | 12                | 48 H          |

=== "MidwaySSD QoS - Dedicated"

    | Partition | Max Nodes/User | Max CPUs/User | Max Jobs/User | Max Wall Time | AllowAccount | QoS     |
    |-----------|--------------------|-------------------|-------------------|---------------|--------------|---------|
    | `ssd`     | 5                | 240               | N/A               | 36 H          | ssd          | ssd     |
    | `ssd`     | 5                | 240               | N/A               | 36 H          | ssd-stu      | ssd-stu | 
    | `ssd-gpu` | N/A                | N/A               | N/A               | 36 H          | ssd          | ssd     | 
    | `ssd-gpu` | N/A                | N/A               | N/A               | 36 H          | ssd-stu      | ssd-stu | 

=== "KICP QoS - Dedicated"

    | Partition | AllowAccount | QoS     | Max Wall Time |
    |-----------|--------------|---------|---------------|
    | `kicp`    | kicp         | kicp    | 48 H          |
    | `kicp-gpu`| kicp         | kicp    | 48 H          |

You may apply for a special allocation if your research requires a temporary exception to a particular limit. Special allocations are evaluated on an individual basis and may or may not be granted.

## Private Partitions (CPP)
These partitions are typically associated with a PI or group of PIs. They can be shared with other PIs or researchers across the University of Chicago and with external collaborators with a Midway account. 

* General Users: Check with your PI for more information. 
* PIs: Private partitions can be purchased via [Cluster Partnership Program](https://rcc.uchicago.edu/support-and-services/cluster-partnership-program){:target="_blank"} to accommodate the needs of your research group. QOS can be tuned at any time by submitting a request.

!!! note
    QoS for private and institutional partitions can be changed upon the owner's request. 
