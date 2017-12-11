# (c) Copyright 2017 Hewlett Packard Enterprise Development LP
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Zing stats generator (output to /var/www/html)
# Needs to be connected to a web server container to report

FROM python:2.7-slim

LABEL version="0.3.1"
LABEL description="zing stats generator"
LABEL maintainer "Stephen Mulcahy <stephen.mulcahy@hpe.com>"

EXPOSE 80

RUN apt-get update && apt-get install -y --no-install-recommends \
        coreutils \
        curl \
        busybox-static \
        git \
    && rm -rf /var/lib/apt/lists/*

# install zing-stats from git repo
COPY zing_stats.py /usr/local/bin/zing_stats.py
COPY zing_stats.html.j2 /usr/local/bin/zing_stats.html.j2
COPY requirements.txt /
RUN pip install --no-cache-dir -r /requirements.txt

# configure and start cron to run zing-stats
RUN mkdir -p /var/spool/cron/crontabs
COPY crontab /root/crontab
RUN /bin/busybox crontab -u root /root/crontab
CMD ["/bin/busybox", "crond", "-f", "-L", "/dev/stdout"]
