# uts-ilab-capstone-2026-Decidr.ai

Project delivery, technical development and assessment evidence for UTS Innovation Lab Capstone Project - Spring 2026.

## Repository layout

    data/          Datasets - not in git, create locally (see below)
    decidr/        Python source code
    docs/          Documentation, decision records, meeting notes
    framework/     Claim definition, credibility criteria, assessment methodology
    notebooks/     Jupyter notebooks for exploration
    references/    Assignment brief, rubric, background reading
    reports/       Written deliverables
    tests/         Test suite

## Setup

Requires [uv](https://docs.astral.sh/uv/).

    # install uv (once)
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # set up the project
    git clone git@github.com:uts-ilab-2026-team/uts-ilab-capstone-2026-Decidr.ai.git
    cd uts-ilab-capstone-2026-Decidr.ai
    uv sync

## Data

Datasets are not committed to this repository. Create the folder locally and add the
release files yourself:

    mkdir -p data/raw data/interim data/processed

Ask the team for the current phase release.

## Team

iLab 14-02 Project Group

- Apaar Agarwal
- Isanka Rashmitha Dissanayake Dissanayake Mudiyanselage
- Mohanned Habib
- Royston Camilo Reis
- Raymond Halim
- Saif Muzaffar Parkar
