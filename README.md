&copy; Copyright 2017 Hewlett Packard Enterprise Development LP

# zing-stats

## Introduction

Tool for generating summary stat reports and graphs from Zing data. Initially using Gerrit data, will consider adding Zuul and Jenkins data also if necessary.

Terminology:
- A change consists of 1 or more revisions (aka patches)
- Each time CI is triggered on a change, a CI run occurs
- A CI run consists of one or more CI jobs e.g. foo-copyright, foo-check and so on

## Screenshots

Example output with projects tab (--project-map specified)
![Screenshot #1](docs/screenshots/projects.png "Screenshot - example output with projects tab (--project-map specified)")

Example output where CI jobs include duration info
![Screenshot #2](docs/screenshots/capacity_duration.png "Screenshot - example output where CI jobs include duration info")

Example output without projects (no projects tabs)
![Screenshot #3](docs/screenshots/no_projects.png "Screenshot - example output without projects (no projects tabs)")

Example output of detailed stats section
![Screenshot #4](docs/screenshots/detailed_stats.png "Screenshot - example output of detailed stats section")

## Installation
### Using virtualenv

1. ```git clone <url to zing-stats repo>```
2. ```sudo apt install virtualenv```
3. ```virtualenv ~/virt_env/zing```
4. ```. ~/virt_env/zing/bin/activate```
5. ```pip install -r requirements.txt```

## Running as script

```
./zing_stats.py --gerrit-host <gerrit url> -o <output directory>
```

The team names used in zing-stats reports are read from projects_teams.json

## Running in docker compose

Uses docker compose to stand up dedicated containers for generation and
reporting.

1. Build the environment,
    ```
    docker-compose build --force-rm --no-cache
    ```
2. Run the environment (detached)
    ```
    docker-compose up -d
    ```
3. attach to running container
    ```
    docker-compose exec zing-stats /bin/bash
    docker-compose exec zing-stats-web /bin/ash
    ```
4. zing-stats output at http://localhost:8172/last_7d/ (may take up to 5 min)


## Testing

```
python setup.py test
```

## Design
General strategy

1. Pull changes data from Gerrit (or a file)
2. Load data into Pandas DataFrames
3. Restrict to range of interest
4. Resample to days or hours
5. Extract stats (count, min, max, avg and so on)
6. Tabulate and plot

## Roadmap / Potential TODO

1. Verify against public Gerrit instances
2. Improve testing
3. Improve setup config
4. Investigate use of Pandas Panels (deprecated) or MultiIndex instead of lots of DataFrames.
5. Add statistics for jobs run (we collect this data, just a case of assembling it)
6. Add in highlighting of out of bounds values in the html report e.g. excessive failure rates in red
7. Other reports/stats requested:
    * how long changes are queued before getting a ci run (may need to query Zuul for this)
    * ci system utilisation/capacity (used total ci hours in the past here, alternative is to aggregate cpu/memory usage stats from the systems)
    * number of Zuul gate queue resets for a change (may need to query Zuul for this)
8. Job duration handling may only work for some Gerrit instances for now, need to determine if better way of gathering that.
9. CI capacity stat relies on job duration data, so this is also unavailable on some Gerrit instances.

## License
This project is licensed under the Apache 2.0 license. Please see [LICENSE](LICENSE) for more info.

## Contributing and feature requests
**Contributing:** You know the drill. Fork it, branch it, change it, commit it, and pull-request it.
We are passionate about improving this project, and glad to accept help to make it better. However, keep the following in mind:

 - You must sign a Contributor License Agreement first. Contact one of the authors (from Hewlett Packard Enterprise) for details and the CLA.
 - We reserve the right to reject changes that we feel do not fit the scope of this project, so for feature additions, please open an issue to discuss your ideas before doing the work.

**Feature Requests:** If you have a need that is not met by the current implementation, please let us know (via a new issue).
This feedback is crucial for us to deliver a useful product. Do not assume we have already thought of everything, because we assure you that is not the case.
