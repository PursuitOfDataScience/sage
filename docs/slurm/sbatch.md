# Batch jobs

The `sbatch` command requests computing resources for non-interactive batch jobs. Rather than requesting resources from the command line, users typically write an `.sbatch` script to request resources for a job and then submit that job to be run on a cluster. A batch job doesn’t require the user to be logged in after submission and ends when either:

1. The program finishes running, 
2. The job's maximum time is reached, 
3. An error occurs. 


## `.sbatch` scripts

In an `.sbatch` script, all Slurm parameters are declared with `#SBATCH` followed by a flag. Here is a sample script you can use to test out the sbatch parameters described below.

Each time you run a script, Slurm gives that particular run a job ID. This sample script creates a .txt file with the job ID as the filename and writes information about the job run to the file. It does this by referencing some of the <a href='https://slurm.schedmd.com/sbatch.html#SECTION_OUTPUT-ENVIRONMENT-VARIABLES' target='_blank'>environment variables</a> Slurm sets when it runs the job.

To set up the sample script, first connect to Midway. Next, create a `job-info.sbatch` file and copy this code into it. Replace `pi-drpepper` in the  `--account=` flag with your group and `jdoe` in the `--mail-user=` flag with your CNet ID. You can also change the `--mail-type=` flag if you don’t want to receive email notifications every step of the way.


===+ "Midway3"
    ```
    #!/bin/bash
    #SBATCH --job-name=job-info
    #SBATCH --output=job-info.out
    #SBATCH --error=job-info.err

    #SBATCH --account=pi-drpepper
    #SBATCH --partition=caslake

    #SBATCH --time=00:03:30

    #SBATCH --nodes=4
    #SBATCH --ntasks-per-node=14

    #SBATCH --mail-type=ALL  # Email notification options: ALL, BEGIN, END, FAIL, ALL, NONE
    #SBATCH --mail-user=jdoe@rcc.uchicago.edu  # Replace jdoe with your CNET and be sure to include "@rcc"

    touch $SLURM_JOB_ID.txt
    echo "Job ID: $SLURM_JOB_ID" >> $SLURM_JOB_ID.txt
    echo "Job name: $SLURM_JOB_NAME" >> $SLURM_JOB_ID.txt
    echo "N tasks: $SLURM_ARRAY_TASK_COUNT" >> $SLURM_JOB_ID.txt
    echo "N cores: $SLURM_CPUS_ON_NODE" >> $SLURM_JOB_ID.txt
    echo "N threads per core: $SLURM_THREADS_PER_CORE" >> $SLURM_JOB_ID.txt
    echo "Minimum memory required per CPU: $SLURM_MEM_PER_CPU" >> $SLURM_JOB_ID.txt
    echo "Requested memory per GPU: $SLURM_MEM_PER_GPU" >> $SLURM_JOB_ID.txt
    ```
=== "MidwaySSD"
    ```
    #!/bin/bash
    #SBATCH --job-name=job-ssd-test
    #SBATCH --output=job-ssd-test.out
    #SBATCH --error=job-ssd-test.err

    #SBATCH --account=ssd
    #SBATCH --partition=ssd         # for ssd-gpu partition, change to --partition=ssd-gpu
    #SBATCH --qos=ssd

    #SBATCH --time=00:03:30

    #SBATCH --nodes=1
    #SBATCH --ntasks-per-node=8

    #SBATCH --mail-type=ALL  # Email notification options: ALL, BEGIN, END, FAIL, ALL, NONE
    #SBATCH --mail-user=jdoe@rcc.uchicago.edu  # Replace jdoe with your CNET and be sure to include "@rcc"

    touch $SLURM_JOB_ID.txt
    echo "Job ID: $SLURM_JOB_ID" >> $SLURM_JOB_ID.txt
    echo "Job name: $SLURM_JOB_NAME" >> $SLURM_JOB_ID.txt
    echo "N tasks: $SLURM_ARRAY_TASK_COUNT" >> $SLURM_JOB_ID.txt
    echo "N cores: $SLURM_CPUS_ON_NODE" >> $SLURM_JOB_ID.txt
    echo "N threads per core: $SLURM_THREADS_PER_CORE" >> $SLURM_JOB_ID.txt
    echo "Minimum memory required per CPU: $SLURM_MEM_PER_CPU" >> $SLURM_JOB_ID.txt
    echo "Requested memory per GPU: $SLURM_MEM_PER_GPU" >> $SLURM_JOB_ID.txt
    ```

Here is an explanation of what each of these parameters means:


|  <div style="width:300px">Option</div>      | Description |
| ----------- | ----------- |
| `--job-name=my_run`     | Assigns name `job-info` to the job.       |
| `--output=my_run.out`   | Writes console output to file `job-info.out`.        |
| `--error=my_run.err`    | Writes error messages to file `job-info.err`.        |
| `--account=pi-drpepper`    | Charges the job to the account `pi-drpepper`     |
| `--partition=caslake`   | Requests compute nodes from the caslake partition on the Midway3 cluster. |
| `--time=1-03:30:00`       | Reserves the computing resources for 1 day, 3 hours, and 30 minutes max (actual time may be shorter if your run completes before this time wall).  | 
| `--nodes=4`             | Requests 4 compute nodes (computers) |
| `--ntasks-per-node=14`  | Requests 14 cores (CPUs) per node, for a total of 14 * 4 = 56 cores. |
| `--mem-per-cpu=2000`    | Requests 2000 MB (2 GB) of memory (RAM) per core, for a total of 2 * 14 = 28 GB per node. |
|`--mail-type=ALL`| Mail events (NONE, BEGIN, END, FAIL, ALL) |
|`--mail-user=jdoe@rcc.uchicago.edu`| Add `rcc.` to your email. |

In this example, we use `sbatch` commands to request 4 compute nodes with 14 CPUs each. This means we are requesting a total of 56 CPUs to our program. The `touch` command creates a file and the `echo` commands write information about the job run to that file.

### Submitting a `.sbatch` script

Continuing the example above, suppose that the sbatch script is saved in the current directory into a file called `job.sbatch`. This script is submitted to the cluster using the following command:
```
sbatch ./job.sbatch
```
or more generally:
```
sbatch ./<your_sbatch_file>
```

You can find more example `.sbatch` submission scripts in the [RCC Slurm workshop materials](https://github.com/rcc-uchicago/SLURM_WORKSHOP){:target='_blank'}.

## Managing jobs
Slurm job scheduler provides several command-line tools for checking on the status of your jobs and for managing them.

### Checking job status
Use the `squeue` (Slurm queue) command to check on the status of jobs. Running `squeue` with no flags will show the full queue (all pending and running jobs.)

To view only the jobs that you have submitted, use the `--user` flag: 
```
squeue --user=<CNetID>
```
For example: 
```
squeue --user=jdoe
```

!!! Note: `0:00` jobs
    Any job with `0:00` in the TIME column is still waiting in the queue. 

To get information about all jobs that are waiting to run on the `gpu` partition, enter:
```
squeue --state=PENDING --partition=gpu
```

To get information about all your jobs that are running on the `gpu` partition, type:
```
squeue --state=RUNNING --partition=gpu --user=<CNetID>
```

To get the estimated start time (if available) of your submitted jobs, use
```
squeue -user $USER  --start
```
or
```
scontrol show job [jobID] | grep StartTime
```

To get what jobs are running on a specific node, like `midway3-0213`
```
squeue -w midway3-0213
```

#### `squeue` status and reason codes

The `squeue` command details a variety of information on an active job’s status with state and reason codes. 

The following tables outline a variety of job states and reason codes you may encounter when using `squeue` to check on your jobs.

##### Job State Codes

| Status        | Code  | Explanation                                                            |
| ------------- | :---: | ---------------------------------------------------------------------- |
| COMPLETED	    | `CD`	| The job has completed successfully.                                    |
| COMPLETING	| `CG`	| The job is finished, but some processes are still active.              |
| FAILED	    | `F`	| The job terminated with a non-zero exit code and failed to execute.    |
| PENDING	    | `PD`	| The job needs resource allocation. It will eventually run.    |
| PENDING	    | `CF`	| The job is being configured. The resources are allocated but are waiting for them to become ready for use. |
| PREEMPTED	    | `PR`	| The job was terminated because of preemption by another job.           |
| RUNNING	    | `R`	| The job is currently allocated to a node and is running.               |
| SUSPENDED	    | `S`	| A running job has been stopped with its cores released to other jobs.  |
| STOPPED	    | `ST`	| A running job has been stopped with its cores retained.                |

A full list of these Job State codes can be found in [Slurm’s documentation](https://slurm.schedmd.com/squeue.html#lbAG){:target='_blank'}.

##### Job Reason Codes

| Reason Code              | Explanation                                                                                     |
| ------------------------ | ----------------------------------------------------------------------------------------------- |
| `AssociationCpuLimit`	   | All CPUs assigned to your job’s specified association are in use; the job will run eventually.  |
| `AssociationMaxJobsLimit`| Maximum number of jobs for your job’s association has been met; the job will run eventually.    |
| `AssociationNodeLimit`   | All nodes assigned to your job’s specified association are in use; the job will run eventually. |
| `Dependency`	           | This job is waiting for a dependent job to complete and will run afterward.                     |
| `InvalidAccount`	       | The job’s account is invalid. Cancel the job and rerun with the correct account.                |
| `InvalidQoS`             | The job’s QoS is invalid. Cancel the job and rerun with the correct account.                    |
| `PartitionCpuLimit`	   | All CPUs assigned to your job’s specified partition are in use; the job will run eventually.    |
| `PartitionMaxJobsLimit`  | Maximum number of jobs for your job’s partition has been met; the job will run eventually.      |
| `PartitionNodeLimit`	   | All nodes assigned to your job’s specified partition are in use; the job will run eventually.   |
| `Priority`	           | One or more higher priority jobs are in queue for running. Your job will eventually run.        |
| `QOSGrpCpuLimit` 	       | All CPUs assigned to your job’s specified QoS are in use; the job will run eventually.          |
| `QOSGrpMaxJobsLimit`	   | Maximum number of jobs for your job’s QoS has been met; the job will run eventually.            |
| `QOSGrpNodeLimit`	       | All nodes assigned to your job’s specified QoS are in use; the job will run eventually.         |
| `QOSMaxJobsPerUserLimit` | The number of jobs you have submitted exceeds the maximum number set by the QoS                 |
| `Resources`	           | The job is waiting for resources to become available and will eventually run.                   |


A full list of these Job Reason Codes can be found [in Slurm’s documentation](https://slurm.schedmd.com/squeue.html#lbAF){:target='_blank'}.

For more information, consult the command-line help by typing `squeue --help`, or visit the [official online documentation](https://slurm.schedmd.com/documentation.html){:target='_blank'}.

### Pausing and resuming submitted jobs

Jobs can be paused using the command:
```
scontrol suspend <job_id>
```
This can be especially useful if a job produces a large output that needs to be moved to a new location before the job finishes.

To resume a suspended job, run the following:
```
scontrol resume <job_id>
```


### Canceling a submitted jobs
To cancel a job you have submitted, use the `scancel` command. This requires you to specify the ID of the job you wish to cancel. 

For example, to cancel a job with ID 8885128, do the following:
```
scancel 8885128
```
If you are unsure what job ID to cancel, see the JOBID column from running `squeue --user=<CNetID>`.

To cancel all jobs you have submitted that are either running or waiting in the queue, enter the following:
```
scancel --user=<CNetID>
```

### Monitoring running jobs
You can monitor your job by connecting to the compute node it runs on via `SSH` and using the `htop` command.

To do this, run the following to see your running jobs and which compute nodes your jobs are running on:
```
squeue --state=RUNNING --user=<CNetID>
```
The last column of the output tells us which nodes are allocated for each job. You can connect to the compute node using the following command, where, for example, we are connecting to the compute node `midway2-0172`.
```
ssh midway2-0172
```
Then, you can view processes running on this compute node, including your job, which will be listed under your CNetID in the USER column, entering the following command: 
```
htop
``` 

### Getting the accounting information of jobs

The `sacct` command displays accounting data for all jobs and job steps in the Slurm job accounting log or Slurm database.

To inquiry the resources used by a job ID (pending, running or terminated), use
```
sacct -j [jobID]
```

!!! tip "Advanced tip"
    You can customize the output of `squeue` and `sacct` by configuring your slurm environment variables:
    ```bash
    export SACCT_FORMAT="jobid,partition,user,account%12,alloccpus,node%12,elapsed,totalcpu,maxRSS,ReqM"
    export SQUEUE_FORMAT="%13i %12j %10P %10u %12a %8T %9r %10l %.11L %5D %4C %8m %N"
    squeue -u cnetid
    ```
    You can put the two export commands into a configuration bash file `set_slurm_env.sh` like [here](https://github.com/rcc-uchicago/R-large-scale/blob/master/set_slurm_env.sh){:target='_blank'}, and `source set_slurm_env.sh` before running `squeue`.

### Monitoring SUs consumed per Job
When the job accepted by the Slurm scheduler is completed or failed, the account specified in the Slurm script is charged for SUs. A user can retrieve info on SUs consumed per job using (need to be logged in to Midway2):
```
rcchelp usage -accounts <account_name> -byjob | grep <user_cnetid>
```
or alternatively:
```
accounts usage -accounts <account_name> -byjob | grep <user_cnetid>
```

## Examples

Below are some example submission scripts you can adapt to run your jobs on Midway. See also the materials from the [RCC Slurm workshop](https://github.com/rcc-uchicago/SLURM_WORKSHOP){:target='_blank'} for additional examples. 

The [SLURM](https://slurm.schedmd.com/documentation.html){:target='_blank'} documentation is always a good reference for all the `#SBATCH` parameters below.


!!! note Sharing scripts with the RCC helpdesk
    If you need help to troubleshoot a Slurm submission script, please ensure that the script is not located in your `/home` or `/scratch` directories that no one except you can access. Instead, please place your script and associated input files in a project directory and set read permission to the group owner `pi-cnetid`.

### Simple jobs

#### A single core job to the standard compute partition

=== "Midway2"
    ```
    #!/bin/bash

    #SBATCH --job-name=single-node-cpu-example
    #SBATCH --account=pi-[group]
    #SBATCH --partition=broadwl  # accessible partitions listed by the sinfo command
    #SBATCH --ntasks-per-node=1  # number of tasks per node
    #SBATCH --cpus-per-task=1    # number of CPU cores per task

    # Load the require module(s)
    module load python

    # match the no. of threads with the no. of CPU cores
    export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK  

    # Load the require module(s)
    python analyze.py
    ```


===+ "Midway3"
    ```
    #!/bin/bash

    #SBATCH --job-name=single-node-cpu-example
    #SBATCH --account=pi-[group]
    #SBATCH --partition=caslake  # accessible partitions listed by the sinfo command
    #SBATCH --ntasks-per-node=1  # number of tasks per node
    #SBATCH --cpus-per-task=1    # number of CPU cores per task

    # Load the require module(s)
    module load python

    # match the no. of threads with the no. of CPU cores
    export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK  

    # Load the require module(s)
    python analyze.py
    ```


#### A single node GPU job to the GPU partition

=== "Midway2"

    ```
    #!/bin/bash

    #SBATCH --job-name=1gpu-example
    #SBATCH --account=pi-[group]
    #SBATCH --partition=gpu2
    #SBATCH --gres=gpu:1
    #SBATCH --ntasks-per-node=1 # num cores to drive each gpu
    #SBATCH --cpus-per-task=1   # set this to the desired number of threads

    # LOAD MODULES
    module load tensorflow
    module load cudnn

    # DO COMPUTE WORK
    export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
    python training.py
    ```

===+ "Midway3"

    ```
    #!/bin/bash

    #SBATCH --job-name=1gpu-example
    #SBATCH --account=pi-[group]
    #SBATCH --partition=gpu
    #SBATCH --gres=gpu:1
    # TO USE V100 specify --constraint=v100
    # TO USE RTX600 specify --constraint=rtx6000
    #SBATCH --constraint=v100   # constraint job runs on V100 GPU use
    #SBATCH --ntasks-per-node=1 # num cores to drive each gpu
    #SBATCH --cpus-per-task=1   # set this to the desired number of threads

    # LOAD MODULES
    module load tensorflow
    module load cudnn

    # DO COMPUTE WORK
    export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
    python training.py
    ```

!!! Notes
    * If your application supports multithreading (e.g., with OpenMP), you want to specify the number of CPU cores per task greater than 1, e.g., `#SBATCH --cpus-per-task=8`
    * You can check the available partitions to your account via the command `rcchelp sinfo` to specify in `--partition`.
    * You can concatenate more than one run in a job script.
    * If the job submission fails, please read the error message carefully: there is information regarding invalid combinations of `partition`, `account`, or `qos` that may help you correct.

### Large-Memory Jobs

If your calculations need more than 60 GB of memory, submit the job to the `bigmem` partition. You can query the technical specification of the partition via the following command: 

```
scontrol show partition bigmem
```
and then `scontrol show node` to find out the memory capacity of its individual nodes.

To submit a job to `bigmem`, include this line in your `.sbatch` script:

```bash
#SBATCH --partition=bigmem
```


### MPI jobs

Many applications use Message Passing Interface (MPI) to improve performance for distributed and parallel computing. For more information on the MPI libraries available on RCC clusters,
run  `module avail openmpi` and `module avail intelmpi`. using more recent modules to compile your codes (e.g., `intelmpi` 2021 and later, `openmpi` 3.0 and later) is recommended. 

Read more about the MPI module [here](../software/compilers.md).

Below is a simple C program (`test-mpi.c`) you can test for your MPI build and the loaded MPI libraries.

```c
#include <stdio.h>
#include <stdlib.h>
#include <mpi.h>

int main(int argc, char *argv[], char *envp[]) {
  int numprocs, rank, namelen;
  char processor_name[MPI_MAX_PROCESSOR_NAME];

  MPI_Init(&argc, &argv);
  MPI_Comm_size(MPI_COMM_WORLD, &numprocs);
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);
  MPI_Get_processor_name(processor_name, &namelen);

  printf("Process %d on %s out of %d\n", rank, processor_name, numprocs);

  MPI_Finalize();
}
```

Copy `test-mpi.c` to your home directory on Midway 2 or 3, load the default OpenMPI module, and compile the program on one of the login nodes:

```default
module load openmpi
mpicc test-mpi.c -o mytest
```

!!! Note
    It is recommended to check that the version of `mpicc` is the one you wanted via `which mpicc`.

Then prepare a job script `test.sbatch` to submit a job to Midway to run the program:

```bash
#!/bin/bash

#SBATCH --job-name=test
#SBATCH --output=test.out
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=28
#SBATCH --partition=broadwl

# Load the default OpenMPI module you used to compile the source file.
module load openmpi

# relax the locked memory limit
ulimit -l unlimited

# Run the MPI program with mpirun. Although the -n flag is not required and
# mpirun will automatically figure out the best configuration from the
# Slurm environment variables, it is recommended to specify -n and/or -ppn
# as explicit as possible.

n=$(( SLURM_NUM_NODES * SLURM_NTASKS_PER_NODE ))
mpirun -n $n --bind-to core --map-by core ./mytest
```

!!! Note
    The options `--bind-to core --map-by core` were added to the `mpirun` command, indicating that the MPI tasks should be bound to physical CPU cores to improve performance.

Submit the MPI job:

```default
sbatch test.sbatch
```

Here is an example output:
```default
Process 1 on midway2-0172.rcc.local out of 56
Process 3 on midway2-0172.rcc.local out of 56
Process 5 on midway2-0172.rcc.local out of 56
...
Process 50 on midway2-0174.rcc.local out of 56
Process 33 on midway2-0174.rcc.local out of 56
```

This output shows that the computation is distributed on four different nodes, with many threads running simultaneously on the same node.

It is recommended to specify the number of tasks per node with the `--ntasks-per-node` option. For example, submitting the job like this:

```default
sbatch --ntasks=56 --ntasks-per-node=1 hellompi.sbatch
```

results in each task running on a different node:

```default
Process 52 on midway2-0175.rcc.local out of 56 
Process 50 on midway2-0173.rcc.local out of 56
Process 49 on midway2-0172.rcc.local out of 56
...
Process 6 on midway2-0017.rcc.local out of 56
Process 21 on midway2-0096.rcc.local out of 56
Process 19 on midway2-0072.rcc.local out of 56
Process 23 on midway2-0100.rcc.local out of 56
```

If you want to minimize the number of nodes by packing as many tasks into a node as possible (which is usually good for reducing communication overhead), then do:

```default
sbatch --nodes=2 --ntasks-per-node=28 hellompi.sbatch
```
<!---
!!! Note
    OpenMPI and IntelMPI can launch MPI programs directly with the Slurm command **srun**. Using this mode for most jobs is unnecessary, but it may provide additional job launch options. For example, from a login node, it is possible to launch the above `hellompi` program using OpenMPI using 28 MPI processes:

    ```default
    srun -n28 hellompi
    ```

    With IntelMPI, you need to also set an environment variable for this to work:

    ```default
    export I_MPI_PMI_LIBRARY=/software/slurm-current-$DISTARCH/lib/libpmi.so
    srun -n28 hellompi
    ```
--->

### Hybrid MPI/OpenMP jobs
The following simple C source code (`test-hybrid.c`) illustrates a hybrid MPI/OpenMP program you can use to test.

```c
#include <stdio.h>
#include <omp.h>
#include "mpi.h"

int main(int argc, char *argv[]) {
  int numprocs, rank, namelen;
  char processor_name[MPI_MAX_PROCESSOR_NAME];
  int iam = 0, np = 1;

  MPI_Init(&argc, &argv);
  MPI_Comm_size(MPI_COMM_WORLD, &numprocs);
  MPI_Comm_rank(MPI_COMM_WORLD, &rank);
  MPI_Get_processor_name(processor_name, &namelen);

  #pragma omp parallel default(shared) private(iam, np)
  {
    np = omp_get_num_threads();
    iam = omp_get_thread_num();
    printf("Hello from thread %d out of %d from process %d out of %d on %s\n",
           iam, np, rank, numprocs, processor_name);
  }

  MPI_Finalize();
}
```

To run the program on the RCC cluster, copy `test-hybrid.c` to your home directory, then compile the code by entering the following commands into a terminal on a login node:

```default
module load openmpi
mpicc -fopenmp test-hybrid.c -o mytest
```

Here, we load the default OpenMPI compiler, but it should be possible to use any available MPI compiler to compile and run this example. Note that the option `-fopenmp` must be used here to compile the program because the code includes OpenMP directives (use `-openmp` or `-qopenmp` for the Intel compiler or `-mp` for the PGI compiler).

Then prepare `test.sbatch` is a submission script that can be used to submit a job to Midway2 to run the `mytest` program. 

```bash
#!/bin/bash

# A job submission script for running a hybrid MPI/OpenMP job on Midway2.
             
#SBATCH --job-name=test
#SBATCH --output=test.out
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=2
#SBATCH --cpus-per-task=8
#SBATCH --partition=caslake

# Load the default OpenMPI module.
module load openmpi

# relax the locked memory limit
ulimit -l unlimited

# Set OMP_NUM_THREADS to the number of CPUs per task we asked for.
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

n=$(( SLURM_NUM_NODES * SLURM_NTASKS_PER_NODE ))
mpirun -np $n ./hellohybrid
```

The options are similar to running an MPI job, with some differences:

* `--nodes=2` specifies the number of nodes.
* `--ntasks-per-node=2` specifies the number of MPI processes (or tasks) per node.
* `--cpus-per-task=8` allocates 8 CPUs for each task.
* `export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK` sets the number of
OpenMP threads to the number of requested cores (CPUs) for each
task.

You can submit `test.sbatch` using the following command from one of the Midway2 login nodes:

```default
sbatch test.sbatch
```

### GPU jobs

There are shared GPU nodes on both Midway2 and Midway3 where you can run GPU-enabled applications. You can check the partition `gpu2` (on `Midway2`) and `gpu` (on Midway3) to see their constituent nodes: 
=== "Midway2"
    ```
    scontrol show partition gpu2
    ```
===+ "Midway3"
    ```
    scontrol show partition gpu
    ```

and then check the features of the individual nodes, for example,
=== "Midway2"
    ```
    scontrol show node midway2-gpu02
    ```
===+ "Midway3"
    ```
    scontrol show node midway3-0278
    ```
which shows NVIDIA Tesla K80, Tesla V100 or Quadro RTX6000 GPUs.

To submit a job to one of the GPU nodes, you must specify the correct partition and the number of GPUs in the `.sbatch` scripts, for example, for job scripts on Midway2:

```bash
#SBATCH --partition=gpu2
#SBATCH --gres=gpu:N
```
where `N` is the number of GPUs requested. Allowable settings for `N` range from 1 to 4, depending on the number of GPUs per node. 

If your application is entirely GPU-driven, you do not need to explicitly request cores, as one CPU core will be assigned by default to act as a master to launch the GPU-based calculation. However, if your application is mixed CPU-GPU, then you will need to request the number of cores with `–ntasks` as is required by your job.

=== "Midway2"

    ```
    #!/bin/bash

    #SBATCH --job-name=1gpu-example
    #SBATCH --account=pi-[group]
    #SBATCH --partition=gpu
    #SBATCH --gres=gpu:1        # number of GPUs per node  
    #SBATCH --ntasks-per-node=1 # number of tasks per node to drive the GPUs in the node
    #SBATCH --cpus-per-task=1   # set this to the desired number of threads

    # LOAD MODULES
    module load tensorflow
    module load cudnn

    # DO COMPUTE WORK
    export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
    python training.py
    ```

===+ "Midway3"

    ```
    #!/bin/bash

    #SBATCH --job-name=1gpu-example
    #SBATCH --account=pi-[group]
    #SBATCH --partition=gpu
    #SBATCH --gres=gpu:1
    # TO USE V100 specify --constraint=v100
    # TO USE RTX600 specify --constraint=rtx6000
    #SBATCH --constraint=v100   # constraint job runs on V100 GPU use
    #SBATCH --ntasks-per-node=1 # num cores to drive each gpu
    #SBATCH --cpus-per-task=1   # set this to the desired number of threads

    # LOAD MODULES
    module load tensorflow
    module load cudnn

    # DO COMPUTE WORK
    export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
    python training.py
    ```

Depending on the software packages you use in the script, their dependency would be the CUDA and OpenACC modules. When you load the modules provided on Midway2 and Midway3 (e.g., `module load tensorflow`), the CUDA dependency modules will be automatically loaded (comparing the output of `module list` before and after doing `module load` command).

If you build the codes using one of those CUDA modules, remember to load these modules in your script. 

An example batch script requests GPU resources, loads the CUDA libraries, and runs the MPI application: In this case, the application `your-app` supports hybrid MPI/GPU parallelization. 

```bash
#!/bin/bash

#SBATCH --job-name=test-gpu   # job name
#SBATCH --output=%N.out       # output log file
#SBATCH --error=%N.err        # error file
#SBATCH --time=01:00:00       # 1 hour of wall time
#SBATCH --nodes=1             # 1 node
#SBATCH --ntasks-per-node=2   # 2 CPU cores to drive the GPUs
#SBATCH --partition=gpu       # gpu partition
#SBATCH --gres=gpu:1          # 1 GPU per node


# Load all required modules below
module load cuda/11.5

ulimit -l unlimited

# Launch your run
mpirun -np 2 ./your-app input.txt
```

### <a name="Job-arrays"></a> Job arrays

Slurm job arrays provide a convenient way to submit a large number of independent processing jobs. For example, Slurm job arrays can be useful for applying the same or similar computation to a collection of data sets. Or, you can launch independent calculations, each with a different set of input parameters, by submitting a single `.sbatch` script. When a job array script is submitted, a specified number of array tasks are created based on the “master” `.sbatch` script. 

Consider the following example (from `array.sbatch`):

```bash
#!/bin/bash

#SBATCH --job-name=array
#SBATCH --output=array_%A_%a.out
#SBATCH --error=array_%A_%a.err
#SBATCH --array=1-16
#SBATCH --time=01:00:00
#SBATCH --partition=caslake
#SBATCH --ntasks=1
#SBATCH --mem=4G

# Print the task id.
echo "My SLURM_ARRAY_TASK_ID: " $SLURM_ARRAY_TASK_ID

# Add lines here to run your computation on each job
./my_app -input $SLURM_ARRAY_TASK_ID
```

In this simple example, `--array=1-16` requests 16 array tasks (numbered 1 through 16). The “array tasks” are copies of the master script automatically submitted to the scheduler on your behalf. In each array task, the environment variable `SLURM_ARRAY_TASK_ID` is set to a unique value (in this example, numbers ranging from 1 to 16). The application should use the array index to handle the corresponding data.

Job array indices can be specified in several different ways. Here are some examples:

```default
# A job array with array tasks numbered from 0 to 31.
#SBATCH --array=0-31
```
or
```
# A job array with array tasks numbered 1, 2, 5, 19, 27.
#SBATCH --array=1,2,5,19,27
```
or
```
# A job array with array tasks numbered 1, 3, 5, and 7.
#SBATCH --array=1-7:2
```

In the example `.sbatch` script above, the `%A_%a` notation is filled in with the master job id (`%A`) and the array task id (`%a`). This is a simple way to create output files in which the file name differs for each job in the array.

The remaining options in the `.sbatch` script are the same as the options used in other, non-array settings; in this example, we are requesting that each array task be allocated 1 CPU (`--ntasks=1`) and 4 GB of memory (`--mem=4G`) on the `broadwl` partition (`--partition=broadwl`) for up to one hour (`--time=01:00:00`).

Most partitions have limits on the number of array tasks that can run simultaneously. Consider parallel batch jobs to achieve a higher throughput.

For more information about Slurm job arrays, refer to [the Slurm documentation on job arrays](https://slurm.schedmd.com/job_array.html){:target='_blank'}.

### <a name="parallel-batch-jobs"></a> Parallel processing jobs

#### GNU Parallel
Computations involving a very large number of independent computations should be combined in some way to reduce the number of jobs submitted to Slurm. We illustrate one strategy for doing this using [GNU Parallel](http://www.gnu.org/software/parallel){:target='_blank'} and **srun**. The **parallel** program executes tasks simultaneously until all tasks have been completed. 

Here’s an example script, `parallel.sbatch`:

```bash
#!/bin/bash

#SBATCH --time=01:00:00
#SBATCH --partition=broadwl
#SBATCH --ntasks=28
#SBATCH --mem-per-cpu=2G  # NOTE DO NOT USE THE --mem= OPTION

# Load the default version of GNU parallel.
module load parallel

# When running a large number of tasks simultaneously, it may be necessary to increase the user process limit.
ulimit -u 10000

# This specifies the options used to run srun. The "-N1 -n1" options are used to allocate a single core to each task.
srun="srun --exclusive -N1 -n1"

# This specifies the options used to run GNU parallel:
#   --delay of 0.2 prevents overloading the controlling node.
#   -j is the number of tasks run simultaneously.
#   The combination of --joblog and --resume create a task log that can be used to monitor progress.

parallel="parallel --delay 0.2 -j $SLURM_NTASKS --joblog runtask.log --resume"

# Run a script, runtask.sh, using GNU parallel and srun. Parallel will run the runtask script for the numbers 1 through 128. To illustrate, the first job will run like this:

# srun --exclusive -N1 -n1 ./runtask.sh arg1:1 > runtask.1

$parallel "$srun ./runtask.sh arg1:{1} > runtask.sh.{1}" ::: {1..128}

# Note that if your program does not take any input, use the -n0 option to call the parallel command:

#   $parallel -n0 "$srun ./run_noinput_task.sh > output.{1}" ::: {1..128}
```

In this example, we aim to run the script `runtask.sh` 128 times. The `--ntasks` option is set to 28, so at most, 28 tasks can be run simultaneously.

Here is the `runtask.sh` script that is run by [GNU Parallel](http://www.gnu.org/software/parallel){:target='_blank'}:

```bash
#!/bin/bash

# This script outputs some useful information so we can see what parallel
# and srun are doing.

sleepsecs=$[ ( $RANDOM % 10 ) + 10 ]s

# $1 is arg1:{1} from GNU parallel.
#
# $PARALLEL_SEQ is a special variable from GNU parallel. It gives the
# number of the job in the sequence.
#
# Here, we print the sleep time, hostname, and the date and time.
echo task $1 seq:$PARALLEL_SEQ sleep:$sleepsecs host:$(hostname) date:$(date)

# Sleep a random amount of time.
sleep $sleepsecs
```

To submit this job, copy `parallel.sbatch` and `runtask.sh` to the same directory, and run `chmod +x
runtask.sh` to make `runtask.sh` executable. Then the job can be submitted to the Slurm queue:

```default
sbatch parallel.sbatch
```

When this job is completed, you should see output files with `runtask.sh.N`, where `N` is between 1 and 128. The content of the first output file (i.e., `runtask.sh.1`) should look something like this:

```default
task arg1:1 seq:1 sleep:14s host:midway2-0002 date:Thu Jan 10 09:17:36 CST 2017
```

Another file `runtask.log` is also created. It gives a list of the completed jobs. (Note: If the `.sbatch` is submitted again, nothing will be run until `runtask.log` is removed.)

Using this same technique to run multithreaded tasks in parallel is also possible. Here is an example `.sbatch` script, `parallel-hybrid.sbatch`, that distributes multithreaded computations (each using 28 CPUs) across two nodes:

```bash
#!/bin/bash

#SBATCH --partition=broadwl
#SBATCH --time=01:00:00
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=28
#SBATCH --exclusive

# Load the default version of GNU parallel.
module load parallel

srun="srun --exclusive -N1 -n1 --cpus-per-task $SLURM_CPUS_PER_TASK"

# Instead of $SLURM_NTASKS, use $SLURM_NNODES to determine how
# many jobs should be run simultaneously.
parallel="parallel --delay 0.2 -j $SLURM_NNODES --joblog runtask.log --resume"

# Run the parallel command.
$parallel "$srun ./runtask.sh arg1:{1} > runtask.sh.{1}" ::: {1..6}
```
#### Launching concurrent processes
Another option for setting up parallel runs is to launch background processes concurrently. This setup would be suitable for independent runs that use a single node exclusively. You can then submit multiple jobs, each on a separate node, if the total number of runs require more cores than on a single node.

```
#!/bin/bash

#SBATCH --partition=broadwl
#SBATCH --time=06:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=12
#SBATCH --exclusive

module load openmpi/4.1.1
mpirun --cpu-set 0-7 --bind-to core -np 8 ./your-mpi-app1 &
mpirun --cpu-set 8-11 --bind-to core -np 4 ./your-mpi-app2 &
wait
```

Here, the first `mpirun` uses 8 CPU cores for eight tasks, and the second uses another 4 CPU cores to avoid oversubscription. The two "&" mean to launch the `mpirun` commands to the background, and the `wait` command ensures all the processes are complete before terminating the job.

A common use case is to launch multiple Python instances with the same script, each processing a set of input parameters:

```
#!/bin/bash

#SBATCH --partition=caslake
#SBATCH --time=06:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=32
#SBATCH --exclusive
#SBATCH --mem=0

module load python

for idx in {0..31}
do
   taskset -c $idx python script.py input-$idx.txt > output-$idx.txt &
done
wait
```

Breakdown:

1. `for idx in {0..31} do ... done`: This loop iterates 32 times, with idx taking values from 0 to 31.

2. `taskset -c $idx`: This command binds the execution of the following command (`python script.py ...`) to a specific CPU core, where `$idx` specifies the core number.

3. `python script.py input-$idx.txt > output-$idx.txt &`: This runs the Python script with a specific input file (`input-$idx.txt`) and writes the output to a corresponding output file (`output-$idx.txt`). The `&` at the end puts each command in the background, allowing them to run in parallel.

4. `wait`: This command makes the script wait until all background processes have finished before it exits

Summary:

The job script parallelizes the execution of script.py across 32 CPU cores, each processing a different input file and saving the results in corresponding output files.


### Dependency jobs

You can schedule jobs depending on the termination status of previously scheduled jobs. This way, you can concatenate your jobs into a pipeline or expand to more complicated dependencies.

For example, `job1.sbatch` is a submission script you plan to submit a batch job:

```bash
#!/bin/bash

#SBATCH --job-name=hellompi
#SBATCH --output=hellompi.out
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=16
#SBATCH --partition=broadwl

# Load the MPI module that was used to build the application
module load openmpi

ulimit -l unlimited

mpirun -np 32 ./hellompi

```

Submit the job script to the Slurm job scheduler from a Midway login node:

```
sbatch job1.sbatch
```

which returns the job ID, for example, `1234567`.

You can then submit another job that is put on the waiting list of the queue (pending)

```
sbatch -dependency=afterany:1234567 job2.sbatch
```

This command indicates that `job2.sbatch` will be put in the queue after the job ID `1234567` is terminated for any reason. The dependency option flag can be `after`, `afterany`, `afterok` and `afternotok`, which are self-explanatory.

For more information on job dependencies, please refer to the [Slurm documentation](https://slurm.schedmd.com/sbatch.html){:target='_blank'}.

### <a name="cron-like-jobs-midway2-legacy"></a> Cron-like jobs - Limited support on Midway2

Cron-like jobs are Slurm jobs submitted to the queue with a specified schedule. These jobs persist until they are canceled or encounter an error. The Midway2 cluster has a dedicated partition, `cron`, for running cron-like jobs. Please contact our [Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'} to request submitting cron-like jobs. These jobs are subject to scheduling limits and resource requested, and will be monitored. We strongly recommend using `dependency jobs` which offer more flexibility and better resource management than using cron-like jobs.

Here is an example of a batch script that internally submits a cron-like job (`cron.sbatch`):

```bash
#!/bin/bash

#SBATCH --time=00:05:00
#SBATCH --output=cron.log
#SBATCH --open-mode=append
#SBATCH --account=cron-account
#SBATCH --partition=cron
#SBATCH --qos=cron

# Specify a valid Cron string for the schedule. This specifies that
# The Cron job runs once per day at 5:15a.
SCHEDULE='15 5 * * *'

# Here is an example of a simple command that prints the hostname and
# the date and time.
echo "Hello on $(hostname) at $(date)."

# This schedules the next run.
sbatch --quiet --begin=$(next-cron-time "$SCHEDULE") cron.sbatch
```

After executing a simple command (print the hostname, date, and time), the script schedules the next run with another call to `sbatch` with the `--begin` option.
