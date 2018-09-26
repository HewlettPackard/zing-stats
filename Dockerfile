# (c) Copyright 2017,2018 Hewlett Packard Enterprise Development LP
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

FROM python:2.7-slim as build
ARG VERSION
RUN ["/bin/bash", "-c", ": ${VERSION:?Expected docker build --build-arg version=xxx ... }"]

RUN apt-get update && apt-get install -y --no-install-recommends \
        coreutils \
        curl \
        busybox-static \
        git \
        virtualenv \
    && rm -rf /var/lib/apt/lists/*

# install zing-stats from git repo
ADD . /build
RUN pip install /build

FROM python:2.7-slim as prod
ARG VERSION
LABEL version=$VERSION
LABEL description="zing stats generator"
LABEL maintainer "Stephen Mulcahy <stephen.mulcahy@hpe.com>"
COPY --from=build /usr/local /usr/local
COPY --from=build /build/crontab /crontab
COPY --from=build /build/projects.json /projects.json
EXPOSE 80
RUN apt-get update && apt-get install -y --no-install-recommends \
        coreutils \
        curl \
        busybox-static \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /var/spool/cron/crontabs
RUN /bin/busybox crontab -u root /crontab
CMD ["/bin/busybox", "crond", "-f", "-L", "/dev/stdout"]
