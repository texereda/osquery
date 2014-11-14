#!/usr/bin/env python
# Copyright 2004-present Facebook. All Rights Reserved.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import argparse
import ast
import json
import logging
import os
import sys
import uuid

from gentable import table, DataType, is_blacklisted

# the log format for the logging module
LOG_FORMAT = "%(levelname)s [Line %(lineno)d]: %(message)s"

CANONICAL_PLATFORMS = {
    "x": "All Platforms",
    "darwin": "Darwin (Apple OS X)",
    "linux": "Ubuntu, CentOS",
}

TEMPLATE_API_DEFINITION = """
/** @jsx React.DOM */
/** This page is automatically generated by genapi.py, do not edit! */

'use strict';

var API = %s;

module.exports = API;

"""


class NoIndent(object):

    """Special instance checked object for removing json newlines."""

    def __init__(self, value):
        self.value = value
        if 'type' in self.value and isinstance(self.value['type'], DataType):
            self.value['type'] = str(self.value['type'])


class Encoder(json.JSONEncoder):

    """
    Newlines are such a pain in json-generated output.
    Use this custom encoder to produce pretty json multiplexed with a more
    raw json output within.
    """

    def __init__(self, *args, **kwargs):
        super(Encoder, self).__init__(*args, **kwargs)
        self.kwargs = dict(kwargs)
        del self.kwargs['indent']
        self._replacement_map = {}

    def default(self, o):
        if isinstance(o, NoIndent):
            key = uuid.uuid4().hex
            self._replacement_map[key] = json.dumps(o.value, **self.kwargs)
            return "@@%s@@" % (key,)
        else:
            return super(Encoder, self).default(o)

    def encode(self, o):
        result = super(Encoder, self).encode(o)
        for k, v in self._replacement_map.iteritems():
            result = result.replace('"@@%s@@"' % (k,), v)
        return result


def gen_api(api):
    """Apply the api literal object to the template."""
    api = json.dumps(
        api, cls=Encoder, sort_keys=True, indent=1, separators=(',', ': ')
    )
    return TEMPLATE_API_DEFINITION % (api)


def gen_spec(tree):
    """Given a table tree, produce a literal of the table representation."""
    exec(compile(tree, "<string>", "exec"))
    columns = [NoIndent({
        "name": column.name,
        "type": column.type,
        "description": column.description,
    }) for column in table.columns()]
    foreign_keys = [NoIndent({"column": key.column, "table": key.table})
                    for key in table.foreign_keys()]
    return {
        "name": table.table_name,
        "columns": columns,
        "foreign_keys": foreign_keys,
        "function": table.function,
        "description": table.description,
    }


def main(argc, argv):
    parser = argparse.ArgumentParser("Generate API documentation.")
    parser.add_argument(
        "--tables", default="osquery/tables/specs",
        help="Path to osquery table specs"
    )
    parser.add_argument(
        "--profile", default=None,
        help="Add the results of a profile summary to the API."
    )
    args = parser.parse_args()

    logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)

    if not os.path.exists(args.tables):
        logging.error("Cannot find path: %s" % (args.tables))
        exit(1)

    profile = {}
    if args.profile is not None:
        if not os.path.exists(args.profile):
            logging.error("Cannot find path: %s" % (args.profile))
            exit(1)
        with open(args.profile, "r") as fh:
            try:
                profile = json.loads(fh.read())
            except Exception as e:
                logging.error("Cannot parse profile data: %s" % (str(e)))
                exit(2)

    # Read in the optional list of blacklisted tables
    blacklist = None
    blacklist_path = os.path.join(args.tables, "blacklist")
    if os.path.exists(blacklist_path):
        with open(blacklist_path, "r") as fh:
            blacklist = fh.read()

    categories = {}
    for base, _, files in os.walk(args.tables):
        for spec_file in files:
            # Exclude blacklist specific file
            if spec_file == 'blacklist':
                continue
            platform = os.path.basename(base)
            platform_name = CANONICAL_PLATFORMS[platform]
            name = spec_file.split(".table", 1)[0]
            if platform not in categories.keys():
                categories[platform] = {"name": platform_name, "tables": []}
            with open(os.path.join(base, spec_file), "rU") as fh:
                tree = ast.parse(fh.read())
                table_spec = gen_spec(tree)
                table_profile = profile.get("%s.%s" % (platform, name), {})
                table_spec["profile"] = NoIndent(table_profile)
                table_spec["blacklisted"] = is_blacklisted(table_spec["name"],
                                                           blacklist=blacklist)
                categories[platform]["tables"].append(table_spec)
    categories = [{"key": k, "name": v["name"], "tables": v["tables"]}
                  for k, v in categories.iteritems()]
    print(gen_api(categories))


if __name__ == "__main__":
    main(len(sys.argv), sys.argv)
