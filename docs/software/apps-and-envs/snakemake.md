# Snakemake

[Snakemake](https://snakemake.readthedocs.io/) is a Python-based workflow management system that lets you define multi-step pipelines as a set of rules, automatically resolving dependencies, parallelizing independent steps, and re-running only what is out of date. It supports local execution, cluster execution via SLURM, and container-based reproducibility.

Keywords: `workflow`, `pipeline`, `bioinformatics`, `automation`, `reproducibility`, `SLURM`

---

## Available modules

<div markdown="1">
===+ "Midway3"
    ```
    -------------------- /software/modulefiles ---------------------
    snakemake/8.24.1(default)  snakemake/9.27.0
    ```
</div>

To see what a module sets up:
```bash
module show snakemake/8.24.1
```

Both versions include:

- `snakemake-executor-plugin-slurm` — submits each rule as a separate SLURM job
- `snakemake-executor-plugin-cluster-generic` — generic cluster backend

---

## Quick start

```bash
module load snakemake       # loads 8.24.1 (default)
snakemake --version
```

---

## Execution modes

### Local execution

Runs all steps on the node where snakemake is launched. Suitable for small workflows or interactive sessions.

```bash
module load snakemake
snakemake --cores 4 --latency-wait 30
```

`--latency-wait 30` is recommended on `/scratch` (Lustre) to allow the filesystem time to propagate newly written output files before Snakemake checks for them.

Example batch script for **Midway3** (`run_snakemake.sh`):
```bash
#!/bin/bash
#SBATCH --job-name=snakemake
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=04:00:00

module load snakemake

cd $SLURM_SUBMIT_DIR
snakemake --cores $SLURM_CPUS_PER_TASK --latency-wait 30 --rerun-incomplete
```

### SLURM executor

Each rule in the workflow becomes an independent SLURM job. Snakemake runs on the **login node** as a lightweight coordinator — it does not run compute work itself.

!!! warning "Run from the login node — not from inside a batch job"
    When using `--executor slurm`, launch Snakemake directly from the login node. Running it inside a batch job causes a warning and may produce unexpected behavior, because the executor attempts to submit jobs while already inside the SLURM environment.

```bash
module load snakemake

snakemake \
  --executor slurm \
  --jobs 20 \
  --default-resources slurm_partition=caslake slurm_account=pi-[cnetid] mem_mb=4000 runtime=60 \
  --latency-wait 60 \
  --rerun-incomplete
```

Key options:

| Option | Description |
|--------|-------------|
| `--jobs N` | Maximum number of SLURM jobs running concurrently |
| `--default-resources` | Default partition, account, memory, and runtime for all rules |
| `--latency-wait 60` | Seconds to wait for output files on Lustre after a job finishes |
| `--rerun-incomplete` | Re-run any jobs that were interrupted mid-execution |

Per-rule resources can override the defaults directly in the Snakefile:
```python
rule my_rule:
    resources:
        mem_mb=8000,
        runtime=120,
        slurm_partition="gpu",
        slurm_extra="--gres=gpu:1"
```

---

## Example Snakefile

A simple 3-level pipeline — generate, process, summarize:

```python
SAMPLES = ["s1", "s2", "s3", "s4"]

rule all:
    input:
        "summary/report.txt"

rule generate:
    output: "raw/{sample}.txt"
    resources: mem_mb=256, runtime=5
    threads: 1
    shell:
        "echo 'sample={wildcards.sample}' > {output}"

rule process:
    input:  "raw/{sample}.txt"
    output: "processed/{sample}.stats"
    resources: mem_mb=512, runtime=10
    threads: 2
    shell:
        "wc -l {input} > {output}"

rule summarize:
    input:  expand("processed/{sample}.stats", sample=SAMPLES)
    output: "summary/report.txt"
    resources: mem_mb=256, runtime=5
    shell:
        "cat {input} > {output}"
```

Run from the login node with the SLURM executor:
```bash
snakemake --executor slurm --jobs 8 \
  --default-resources slurm_partition=caslake slurm_account=pi-[cnetid] mem_mb=512 runtime=10 \
  --latency-wait 60
```

---

## Notes

- **Login node execution**: When using `--executor slurm`, Snakemake itself must run on the login node. It is a lightweight coordinator process — it only polls job status and submits new jobs; actual compute work runs in the dispatched SLURM jobs.
- **`--jobs` is not CPUs**: `--jobs` limits the number of concurrently submitted SLURM jobs, not CPU cores. Set it to a reasonable value (e.g., 20–50) to avoid flooding the scheduler.
- **Lustre latency**: Always use `--latency-wait 30` (local) or `--latency-wait 60` (SLURM executor) on `/scratch` to avoid false "missing output" errors caused by Lustre metadata propagation delays.
- **Interrupted runs**: Use `--rerun-incomplete` to safely re-run any rules that were interrupted (e.g., by a timeout or cancelled job) without re-running already-completed steps.
- **Dry run**: Preview what Snakemake will do without executing anything:
  ```bash
  snakemake --executor slurm --jobs 8 ... --dry-run
  ```
- **Version 9.x changes**: Snakemake 9.x reorganized some plugin interfaces. Workflows written for 8.x are generally compatible but should be tested. Use `module load snakemake/8.24.1` to pin to the stable release.
