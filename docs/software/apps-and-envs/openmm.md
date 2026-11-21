# OpenMM

[OpenMM](https://openmm.org/) is an open-source high-performance toolkit for molecular simulation. You can use it as an application, a library, or a flexible programming environment.

Keywords: `biology`, `physics`, `chemistry`, `molecular dynamics`


## Available modules
There are several OpenMM modules on Midway3 that you can check via `module avail openmm`:

===+ "Midway3"
    ```
    ---------------------------- /software/modulefiles -----------------------------
    openmm/7.5.1  openmm/8.1.0(default)

    ```

???+ note
    OpenMM is under active development. You are encouraged to build the latest stable version from [source code](https://github.com/openmm/openmm) in your own space using the provided [compilers](../compilers.md).

???+ note
    You can also install OpenMM into your conda environment. See the [OpenMM User Guide](https://docs.openmm.org/latest/userguide/application.html) for more information.
    ```
    module load python/miniforge-25.3.0
    conda create -n your-env python=3.8
    source activate your-env
    conda install -c conda-forge openmm cudatoolkit=11.5
    ```

The [OpenMM documentation](https://docs.openmm.org/) contains useful information for improving the performance of your specific calculations.


## Example job scripts

The following is an example batch script for running OpenMM on Midway3:

```
#!/bin/bash
#SBATCH --job-name=openmm-bench
#SBATCH --account=pi-[cnetid]
#SBATCH --time=01:00:00
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --constraint=v100
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1

module load openmm

cd $SLURM_SUBMIT_DIR

python run_openmm.py
```
where `run_openmm.py` is a Python script that sets up the system.

Example Python scripts can be found in the [OpenMM GitHub repository](https://github.com/openmm/openmm/blob/master/examples/). Below is an example script that reads in a protein PDB structure, selects a force field, defines a system, specifies a time integrator, performs energy minimization, sets up the output log and snapshots, and finally runs the MD simulation. You can use this script as `run_openmm.py` in the job script above.

```
from openmm.app import *
from openmm import *
from openmm.unit import *
from sys import stdout

pdb = PDBFile('input.pdb')
forcefield = ForceField('amber14-all.xml', 'amber14/tip3pfb.xml')
system = forcefield.createSystem(pdb.topology, nonbondedMethod=PME, nonbondedCutoff=1*nanometer, constraints=HBonds)
integrator = LangevinMiddleIntegrator(300*kelvin, 1/picosecond, 0.004*picoseconds)

# Select a platform for GPU acceleration: 
# The CUDA backend might fail if the GPU driver on the compute nodes is incompatible with the PTX that OpenMM was compiled with
platform_name = ''
try:
    platform_name = 'CUDA'
    simulation = Simulation(pdb.topology, system, integrator,
                            openmm.Platform.getPlatformByName(platform_name))
except OpenMMException as e:
    platform_name = 'OpenCL'
    simulation = Simulation(pdb.topology, system, integrator,
                            openmm.Platform.getPlatformByName(platform_name))
except Exception:
    platform_name = 'CPU'
    simulation = Simulation(pdb.topology, system, integrator)

print(f'Running simulation on the {platform_name} backend')

simulation.context.setPositions(pdb.positions)
simulation.minimizeEnergy()
simulation.reporters.append(PDBReporter('output.pdb', 1000))
simulation.reporters.append(StateDataReporter(stdout, 1000, step=True, potentialEnergy=True, temperature=True))
simulation.step(10000)
```

## Getting help

- Official documentation: [OpenMM documentation](https://docs.openmm.org/){:target='_blank'} and [OpenMM examples](https://github.com/openmm/openmm/tree/master/examples){:target='_blank'}
- Built-in help: `python -m openmm.testInstallation` to check the available platforms
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
