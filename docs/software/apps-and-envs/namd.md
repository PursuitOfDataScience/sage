# [NAMD](http://www.ks.uiuc.edu/Research/namd/)

[NAMD](http://www.ks.uiuc.edu/Research/namd/)  is a parallel molecular dynamics code designed for high-performance simulation of large biomolecular systems.

Keywords: `biology`, `physics`, `chemistry`, `molecular dynamics`

## Available modules

There are several NAMD modules on Midway2 and Midway3 that you can check via `module avail namd`:

=== "Midway2"
    ```
    ---------------------------- /software/modulefiles2 ----------------------------
    namd/2.11+intelmpi-5.1+intel-16.0 
    namd/2.12+intelmpi-5.1+intel-16.0
    namd/2.13+intelmpi-5.1+intel-16.0
    namd/2.14+intelmpi-5.1+intel-16.0   

    ```
===+ "Midway3"
    ```
    ---------------------------- /software/modulefiles -----------------------------
    namd/2.14(default)
    namd/2.14+intel-2022.0
    namd/2.14+intel-2022.0+cuda-11.5
    namd/2.14+intel-2022.0+cuda-11.5+multi
    namd/2.14+intel-2022.0+multi
    namd/3.0b3-multicore-cuda
    namd/3.0b5-netlrts-smp-cuda
    namd/3.0b5-verbs-smp-cuda
    ```
The `multi` suffix indicates that the module can run across multiple nodes. The `cuda-11.5` indicates that the module support GPU acceleration via CUDA. You can then show the dependency of individual modules, for example, on Midway3 if you do
```
module show namd/2.14+intel-2022.0+multi
```
you will get
```
-------------------------------------------------------------------
/software/modulefiles/namd/2.14+intel-2022.0+multi:

module-whatis   {setup namd 2.14 multiple-node compiled with intel-2022.0}
conflict        namd
module          load intelmpi/2021.5+intel-2022.0
prepend-path    PATH /software/namd-2.14-el8-x86_64+intel-2022.0/bin-multi
setenv          FI_PROVIDER mlx
setenv          NAMD_HOME /software/namd-2.14-el8-x86_64+intel-2022.0/bin-multi
setenv          CONV_RSH ssh
```

In this case you can see this module was compiled with `intelmpi/2021.5+intel-2022.0`. 

## Example job scripts

An example batch script to run NAMD 2.14 for Midway3 with multiple nodes and GPU acceleration is given as below
```
#!/bin/bash
#SBATCH --job-name="test-namd"
#SBATCH --account=pi-[cnetid]
#SBATCH -t 06:00:00
#SBATCH --partition=gpu
#SBATCH --nodes=2             # 2 nodes
#SBATCH --ntasks-per-node=2   # 2 processes per node
#SBATCH --cpus-per-task=2     # 2 threads mapping to 2 cores per node
#SBATCH --gres=gpu:2          # 2 GPUs per node
#SBATCH --constraint=v100

module load namd/2.14+intel-2022.0+cuda-11.5+multi

ulimit -l unlimited

# calculate total processes (P) and cpus per task
P=$(( SLURM_NTASKS_PER_NODE * SLURM_NNODES ))
CPUSPERPE=$SLURM_CPUS_PER_TASK

# using 4 processes, 2 worker threads per process (8 PEs total) using PEs 0,2,4,6 for communication
mpirun -np $P $NAMD_HOME/namd2 +ppn $CPUSPERPE +pemap 1,3,5,7 +commap 0,2,4,6 +devices 0,1 +ignoresharing +isomalloc_sync input.namd
```

The following script shows how to run NAMD 2.14 for a replica exchange simulation for 2 replicas, each on a node, using 1 GPU.

```
#!/bin/bash
#SBATCH --job-name="test-namd"
#SBATCH --account=pi-[cnetid]
#SBATCH -t 06:00:00
#SBATCH --partition=gpu
#SBATCH --nodes=2             # 2 nodes
#SBATCH --ntasks-per-node=1   # 1 process per node
#SBATCH --cpus-per-task=4     # 4 threads mapping to 4 cores per node
#SBATCH --gres=gpu:1          # 1 GPU per node
#SBATCH --constraint=v100

module load namd/2.14+intel-2022.0+cuda-11.5+multi

ulimit -l unlimited

# calculate total processing elements (PE)
PPN=$SLURM_CPUS_PER_TASK
P=$(( SLURM_NTASKS_PER_NODE * SLURM_NNODES ))

# create separate folders for the output of M=2 replicas
mkdir -p output
(cd output; mkdir -p {0..1})

# run a simulation with M=2 replicas
mpirun -np $P $NAMD_HOME/namd2 +ppn $PPN +replicas 2 apoa1.namd +stdout output/%d/mysum.%d.log
```

The following script shows how to run NAMD 3.0, which is a single-node, multithreading, GPU resident version.

```
#!/bin/bash
#SBATCH --job-name="test-namd"
#SBATCH --account=pi-[cnetid]
#SBATCH -t 06:00:00
#SBATCH --partition=gpu
#SBATCH --nodes=1             # 1 node
#SBATCH --ntasks-per-node=1   # 1 process per node
#SBATCH --cpus-per-task=4     # 4 threads mapping to 4 cores per node
#SBATCH --gres=gpu:2          # 2 GPUs per node
#SBATCH --constraint=v100

module load namd/3.0b3-multicore-cuda

# calculate total processes (P) and procs per node (PPN)
PPN=$(( $SLURM_CPUS_PER_TASK * $SLURM_NTASKS_PER_NODE ))
P=$(( $PPN * $SLURM_NNODES ))

$NAMD_HOME/namd3 +p $PPN +devices 0,1 --CUDASOAIntegrate on +setcpuaffinity input.namd
```

The following script shows how to run NAMD 3.0 for a replica exchange simulation on a single node, for 2 replicas each on a GPU.

```
#!/bin/bash
#SBATCH --job-name="test-namd"
#SBATCH --account=pi-[cnetid]
#SBATCH -t 06:00:00
#SBATCH --partition=gpu
#SBATCH --nodes=1             # 1 node
#SBATCH --ntasks-per-node=1   # 1 process per node
#SBATCH --cpus-per-task=4     # 4 threads mapping to 4 cores per node
#SBATCH --gres=gpu:2          # 2 GPUs per node, 1 for each replica
#SBATCH --constraint=v100

module load namd/3.0b5-netlrts-smp-cuda

# Generate NAMD nodelist
echo "group main" > nodelist.$SLURM_JOBID
for n in `echo $SLURM_NODELIST | scontrol show hostnames`; do
  echo "host $n" >> nodelist.$SLURM_JOBID
done

NODELIST=nodelist.$SLURM_JOBID

ulimit -l unlimited

# calculate total processing elements (PE)
PPN=$SLURM_CPUS_PER_TASK

# create separate folders for the output of M=2 replicas
mkdir -p output
(cd output; mkdir -p {0..1})

# run a simulation with M=2 replicas
$NAMD_HOME/charmrun $NAMD_HOME/namd3 ++local +p $PPN +replicas 2 +devicesperreplica 1 +ignoresharing apoa1.namd +stdout output/%d/mysum.%d.log
```
<!---
`namd.sbatch` is a submission script that can be used to submit
the `apoa1.namd` calculation job to the queue.

```bash
#!/bin/sh

#SBATCH --job-name=namd
#SBATCH --output=namd-%j.out
#SBATCH --constraint=ib
#SBATCH --exclusive
#SBATCH --nodes=4

module load namd/2.9

mpirun namd2 apoa1.namd
```

The script can be submitted with this command:

```default
sbatch namd.sbatch
```
--->