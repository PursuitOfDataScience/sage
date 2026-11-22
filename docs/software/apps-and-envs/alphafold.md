# AlphaFold

[AlphaFold](https://github.com/google-deepmind/alphafold) is an artificial intelligence program developed by Google DeepMind that predicts protein structures with high accuracy. This page provides instructions for running **AlphaFold 2** and **AlphaFold 3** on Midway3.

Keywords: `structural biology`, `protein structure prediction`, `deep learning`, `bioinformatics`

---

## Available modules

AlphaFold 2 and 3 are available as modules on Midway3. You can check the available versions using the following command:

```bash
module avail alphafold
```
Output:

```
---------------------- /software/modulefiles----------------------------------
alphafold/2.0.0  alphafold/2.2.0  alphafold/2.3.2(default)  alphafold/3.0.0  alphafold/3.0.1  alphafold/3.0.2  alphafold/3.0.3
```

### AlphaFold 2
AlphaFold 2 source code and running scripts (e.g., `run_alphafold.py`) can be found on the [AlphaFold GitHub repository](https://github.com/deepmind/alphafold).

The reference datasets for different versions of AlphaFold are accessible under (see also [AlphaFold/ColabFold datasets](../../data_sharing/databases/alphafold.md)):
- `/software/alphafold-data/`
- `/software/alphafold-data-2.2/`
- `/software/alphafold-data-2.3/`

---

### AlphaFold 3
AlphaFold 3 on Midway3 uses a container-based approach with **Singularity** (or Apptainer) and requires different input arguments compared to AlphaFold 2. It supports advanced features like **FlashAttention** and improved accuracy for protein-ligand and protein-DNA interactions. See the example job script below for usage details.

---

### Key differences between AlphaFold 2 and AlphaFold 3

AlphaFold 2 (2020–21) predicts the 3D structure of single protein chains, and later of protein complexes through AlphaFold-Multimer. AlphaFold 3 (2024) extends structure prediction to almost any biomolecular complex. The main differences between AlphaFold 2 (AF2) and AlphaFold 3 (AF3) are as follows:

#### 1. What structures it is designed to predict

* AF2: Proteins only. Ligands, nucleic acids, ions and modifications are left out.
* AF3: Proteins, DNA, RNA, small-molecule ligands, ions and modified residues (glycosylation, phosphorylation and so on), all predicted together in one complex. This is the biggest practical change, because drug–target and protein–nucleic-acid interactions are now in scope.

#### 2. Architecture

* AF2: The core is the Evoformer, which leans heavily on the multiple sequence alignment (MSA). A structure module then builds the 3D structure from per-residue frames, side-chain torsion angles and “invariant point attention.”
* AF3: The Evoformer is replaced by the Pairformer. It works mainly on the pair representation, and MSA processing is cut down to a small, lighter module. The structure module is replaced by a diffusion module that predicts raw atom coordinates directly. It starts from noise and refines step by step, with no frames or torsion angles. That lets it handle arbitrary chemistry without rules written for each molecule type.

#### 3. Generative vs. deterministic output

* AF2: Gives one prediction per run (you can vary the seed or model weights).
* AF3: Because it uses diffusion, it is a generative model. It can sample several plausible structures. The downside is that it can “hallucinate” structure in disordered regions. DeepMind reduced this by training on AF2 predictions, so disordered regions come out as extended loops instead of fake helices.

#### 4. Confidence measures

Both report pLDDT (predicted Local Distance Difference Test) and PAE (Predicted Aligned Error). AF3 adds a PDE (Predicted Distance Error) head and gets its confidence estimates from a mini-rollout of the diffusion process.

Quick rule of thumb:

* Is this region folded correctly? Use pLDDT.
* Is the overall fold right? Use pTM.
* Are these domains or chains arranged correctly? Use PAE and ipTM.
* Are these two parts the right distance apart? Use PDE (AF3 only)

#### 5. Accuracy

AF3 often outperforms specialized docking tools, such as Vina, on protein–ligand benchmarks like PoseBusters, even though it is not given the binding pocket structure.
It also improves on AF-Multimer for protein–protein interactions, and especially for antibody–antigen interfaces.
For single-chain proteins, the gains over AF2 are modest.

#### 6. Access and licensing

* AF2: Fully open source (Apache 2.0) with weights included. That openness drove huge community use and the AlphaFold DB of about 200M predicted structures.
* AF3: Launched in May 2024 only through the web-based AlphaFold Server, which had limits on ligands and daily jobs. The model weights are only available on request and for non-commercial academic use. This led to open reproductions such as Boltz-1/2, Chai-1 and Protenix.

### System requirements

#### AlphaFold 2
- **GPU:** V100 or higher (NVIDIA GPU with compute capability ≥8.0 recommended)
- **CUDA:** Version 11.3 or higher
- **Memory:** 32GB RAM minimum (64GB recommended for large proteins or multiple jobs)

#### AlphaFold 3
- **GPU:** A100 or higher recommended (80GB GPU RAM may be needed for very large inputs)
- **CUDA:** Version 12.3 or higher (CUDA 12.6 preferred for best accuracy; 12.2 may work, but not guaranteed)
- **Memory:** 32GB RAM minimum (more is better for large jobs and databases)

??? note "Why Container-Based Approach for AlphaFold 3?"
    AlphaFold 3 requires CUDA 12.3 or higher, but the system NVIDIA driver version is 12.2. Using a container bypasses the driver compatibility issue.

    *This guide will be updated with a module-based usage method for AlphaFold 3 in the future, as the system CUDA version is updated.*

In short, AF2 solved the single-protein folding problem. AF3 aims to model the entire interacting biomolecular system, and it got there by moving from a geometry-specific structure module to a general diffusion-based generator. The cost is more restrictive access and a new risk of hallucinated structure.


| Feature                | AlphaFold 2                          | AlphaFold 3                          |
|------------------------|---------------------------------------|---------------------------------------|
| Input Format           | `.fasta` file                       | `.json` file                         |
| Execution Environment  | Python-based scripts                | Singularity container                |
| GPU Requirements       | Moderate GPU memory (e.g., V100)    | High GPU memory (e.g., 2 A100 GPUs)  |
| FlashAttention Support | Not available                       | Supported (`triton` or `xla`)        |


---

## Example job scripts

### AlphaFold 2
The following example demonstrates how to run AlphaFold 2 on a GPU node with 2 GPUs and up to 16 CPU cores for multithreading on Midway3.

```bash
#!/bin/bash
#SBATCH --job-name=alphafold2
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --time=04:00:00
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:2
#SBATCH --constraint=v100
#SBATCH --mem=64G

module load alphafold/2.3.2 cuda/11.3

cd $SLURM_SUBMIT_DIR

DOWNLOAD_DATA_DIR=/software/alphafold-data-2.3

python run_alphafold.py \
  --data_dir=$DOWNLOAD_DATA_DIR  \
  --uniref90_database_path=$DOWNLOAD_DATA_DIR/uniref90/uniref90.fasta  \
  --mgnify_database_path=$DOWNLOAD_DATA_DIR/mgnify/mgy_clusters_2022_05.fa  \
  --bfd_database_path=$DOWNLOAD_DATA_DIR/bfd/bfd_metaclust_clu_complete_id30_c90_final_seq.sorted_opt  \
  --uniref30_database_path=$DOWNLOAD_DATA_DIR/uniref30/UniRef30_2021_03 \
  --pdb70_database_path=$DOWNLOAD_DATA_DIR/pdb70/pdb70  \
  --template_mmcif_dir=$DOWNLOAD_DATA_DIR/pdb_mmcif/mmcif_files  \
  --obsolete_pdbs_path=$DOWNLOAD_DATA_DIR/pdb_mmcif/obsolete.dat \
  --model_preset=monomer \
  --max_template_date=2022-1-1 \
  --db_preset=full_dbs \
  --use_gpu_relax=true \
  --output_dir=out_alphafold_2.1.1_multi-monomer \
  --fasta_paths=T1083.fasta,T1084.fasta
```

---

### AlphaFold 3
The following example demonstrates how to run AlphaFold 3 using a `.json` input file (e.g., `nipah_zmr.json`) on a GPU node with 2 A100 GPUs.

```bash
#!/bin/bash
#SBATCH --job-name=alphafold3
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --time=04:00:00
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:2
#SBATCH --constraint=a100
#SBATCH --mem=32G

module load apptainer

cd $SLURM_SUBMIT_DIR

# Set the path to the AlphaFold 3 database directory
DOWNLOAD_DATA_DIR=/software/alphafold3.0-el8-x86_64/databases  # Path to AlphaFold 3 database directory

# Define bind paths
export BIND_PATHS="$DOWNLOAD_DATA_DIR,/software/alphafold3.0-el8-x86_64/params,/software/alphafold3.0-el8-x86_64/singularity,/tmp/$USER,/home/$USER,/scratch/midway3/$USER"

# Run the Singularity container
singularity exec --nv \
    -B "$BIND_PATHS" \
    --env CUDA_VISIBLE_DEVICES=0,1,NVIDIA_VISIBLE_DEVICES=0,1 \
    /software/alphafold3.0-el8-x86_64/alphafold3.sif \
    python /app/alphafold/run_alphafold.py \
    --json_path=/home/$USER/nipah_zmr.json \
    --db_dir=$DOWNLOAD_DATA_DIR \
    --output_dir=/scratch/midway3/$USER/alphafold3_output \
    --model_dir=/software/alphafold3.0-el8-x86_64/params \
    --flash_attention_implementation=triton \
    --run_data_pipeline=True \
    --run_inference=True \
    --jackhmmer_n_cpu=8 \
    --nhmmer_n_cpu=8
```

---

### Input file preparation

#### AlphaFold 2
- Input format: `.fasta` file containing the protein sequence(s).
- Example:
  ```
  >T1083
  SEQUENCE1
  >T1084
  SEQUENCE2
  ```

#### AlphaFold 3
- Input format: `.json` file containing the protein sequence(s) and metadata.
- Example:
  Download the example file `nipah_zmr.json` from [this link](https://www.rbvi.ucsf.edu/chimerax/data/af3-wynton-dec2024/nipah_zmr.json) and place it in your home directory (`/home/$USER`).

---

## Troubleshooting

1. **Error**: `Unknown backend: 'gpu' requested, but no platforms that are instances of gpu are present.`
     - **Solution**: Ensure the job is running on a GPU-enabled node and that the `CUDA_VISIBLE_DEVICES` environment variable is set correctly.

2. **Error**: `Failed to get mmCIF for <PDB_ID>.`
     - **Solution**: Verify that the database directory is accessible and contains the required files, e.g., with `ls -l /software/alphafold3.0-el8-x86_64/databases`. If you use your own copy of the databases, ensure proper permissions:
     ```bash
     chmod 755 --recursive /path/to/your/databases
     ```

3. **Error**: `implementation='triton' for FlashAttention is unsupported on this GPU generation.`
     - **Solution**: Switch to the `xla` implementation:
     ```bash
     --flash_attention_implementation=xla
     ```

4. **Error**: `CUDA version mismatch.`
     - **Solution**: Ensure the NVIDIA driver and CUDA versions are compatible with AlphaFold3. Update the driver if necessary. For instance, if `nvidia-smi` on the node shows
     ```
     NVIDIA-SMI 535.161.08             Driver Version: 535.161.08   CUDA Version: 12.2     
     ```
     it means that the GPU driver version is 535.161.08, which was installed along with the CUDA toolkit version 12.2. If a version of AlphaFold3 relies on CUDA toolkit 12.x (where x > 2), make sure that GPU driver 535.161.08 is also compatible with that CUDA version.

---

### Additional notes

- **Resource allocation**: Adjust the `--gres=gpu` and `--mem` parameters in the job script based on the size of the input data.
- **Output directory**: Results will be saved in the directory specified by the `--output_dir` parameter.

## Getting help

- Official documentation: [AlphaFold 2 GitHub repository](https://github.com/google-deepmind/alphafold){:target='_blank'} and [AlphaFold 3 GitHub repository](https://github.com/google-deepmind/alphafold3){:target='_blank'}
- Built-in help: `python run_alphafold.py --help`
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
