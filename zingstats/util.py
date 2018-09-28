#
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


import logging
import sys


def configure_logging(args):
    """Configure logging.

    - Default => INFO
    - log_quietly (-q) => ERROR
    - log_verbosely (-v) => DEBUG
    """

    # requests and urllib3 are very chatty by default, suppress some of this
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    # and suppress InsecurePlatformWarning from urllib3 also
    # see http://stackoverflow.com/questions/29099404 for details
    import requests.packages.urllib3
    requests.packages.urllib3.disable_warnings()

    # Set root logger level to DEBUG, and use the
    # handler level to control verbosity.
    logging.getLogger().setLevel(logging.DEBUG)

    ch = logging.StreamHandler(stream=sys.stderr)
    ch.setLevel(logging.INFO)
    if args.log_quietly:
        ch.setLevel(logging.ERROR)
    elif args.log_verbosely:
        ch.setLevel(logging.DEBUG)

    ch_format = logging.Formatter('%(message)s')
    ch.setFormatter(ch_format)
    logging.getLogger().addHandler(ch)

    if args.logfile:
        fh = logging.FileHandler(args.logfile, delay=True)
        fh.setLevel(logging.INFO)
        if args.log_trace:
            fh.setLevel(logging.DEBUG)
        log_format = (
            '%(asctime)s: %(process)d:%(thread)d %(levelname)s - %(message)s'
        )
        fh_format = logging.Formatter(log_format)
        fh.setFormatter(fh_format)
        logging.getLogger().addHandler(fh)
