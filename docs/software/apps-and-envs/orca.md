# ORCA

[ORCA](https://www.faccts.de/orca/) is a general-purpose quantum chemistry package that supports a wide variety of methods such as density functional theory, many-body perturbation theory, and coupled cluster. ORCA is free of charge for academic use, but not open source.

Check out the [ORCA manual](https://www.faccts.de/docs/orca/6.0/manual/) for more information.

Keywords: `quantum chemistry`, `chemistry`

## Available modules
There are several ORCA modules on Midway3 that you can check via `module avail orca`:

===+ "Midway3"
    ```
    ---------------------------- /software/modulefiles -----------------------------
    orca/4.1  orca/4.2.1  orca/5.0.2(default)  orca/6.0.1  
    orca/4.2  orca/5.0.0  orca/5.0.4
    ```

You can use `module show` to see the dependencies and environment variables set by a specified `orca` module, for example, `module show orca/6.0.1`:

```
-------------------------------------------------------------------
/software/modulefiles/orca/6.0.1:

module-whatis   {setup orca 6.0.1 compiled with the system compiler}
conflict        orca
module          load openmpi/4.1.2+gcc-10.2.0
prepend-path    PATH /software/orca-6.0.1-el8-x86_64/bin
setenv          ORCA_DIR /software/orca-6.0.1-el8-x86_64/bin
-------------------------------------------------------------------
```


## Example job scripts

An example batch script to run ORCA on Midway3 is given below:

```
#!/bin/bash
#SBATCH --job-name=orca-bench
#SBATCH --account=pi-[cnetid]
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=8
#SBATCH --mem=64GB

module load orca/6.0.1

ulimit -l unlimited

cd $SLURM_SUBMIT_DIR

# the environment variable ORCA_DIR may be set by the orca module loaded
$ORCA_DIR/orca input.txt > output.log
```

Note that ORCA supports MPI parallelization with a compatible version of OpenMPI. For the given example, `orca/6.0.1` is compatible with OpenMPI 4.1.x. Here, the binary `orca` will launch 8 MPI processes as specified in the `%pal` section of the input script `input.txt`. Below is a simple input script that performs a single-point Hartree-Fock calculation with the DEF2-SVP basis set using 8 MPI processes (add the `Opt` keyword for a geometry optimization).

```

%pal
    nprocs 8
end
!HF DEF2-SVP
%scf
   maxiter 500
end
* xyz 0 1
O   0.0000   0.0000   0.0626
H  -0.7920   0.0000  -0.4973
H   0.7920   0.0000  -0.4973
*
```

## Getting help

- Official documentation: [ORCA manual](https://www.faccts.de/docs/orca/6.0/manual/){:target='_blank'} and [ORCA forum](https://orcaforum.kofo.mpg.de/){:target='_blank'}
- Built-in help: `module show orca/6.0.1`
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
