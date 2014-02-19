# Copyright 2010 Jacob Kaplan-Moss

# Copyright 2011 OpenStack Foundation
# Copyright 2013 IBM Corp.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from __future__ import print_function

import argparse
import copy
import datetime
import getpass
import locale
import os
import sys
import time

import six

from lbaasclient import exceptions
from lbaasclient.openstack.common import strutils
from lbaasclient.openstack.common import timeutils
from lbaasclient import utils
from lbaasclient.v1_0 import quotas
from lbaasclient.v1_0 import loadbalancers


def _key_value_pairing(text):
    try:
        (k, v) = text.split('=', 1)
        return (k, v)
    except ValueError:
        msg = "%r is not in the format of key=value" % text
        raise argparse.ArgumentTypeError(msg)


def _create(cs, args):
    """Create a new loadbalancer."""
    #print(args)
    if not args.name:
        raise exceptions.CommandError("you need to specify a name")

    boot_args = [args.name, args.protocol, args.vip_type]
    #print(boot_args)

    boot_kwargs = dict(
            port=args.port,
            algorithm=args.algorithm,
            nodes=args.node)

    return boot_args, boot_kwargs


@utils.arg('name', metavar="<name>", help="Name for the new loadbalancer")
@utils.arg('--algorithm',
     default=None,
     metavar='<algorithm>',
     help="Loadbalancing Algorithm to use")
@utils.arg('--vip-type',
     default="PUBLIC",
     metavar='<vip_type>',
     help="Type of virtualIp to add")
@utils.arg('--protocol',
     default="HTTP",
     metavar='<protocol>',
     help="Protocol of the service which is being load balanced")
@utils.arg('--port',
     type=int,
     default=None,
     metavar='<port>',
     help="Port on which to accept connections")
@utils.arg('--node',
     metavar="<key=value>",
     action='append',
     default=[],
     help="Node IP")
@utils.arg('--poll',
     dest="poll",
     action="store_true",
     default=False,
     help='Blocks while loadbalancer builds so progress can be reported.')

def do_create(cs, args):
    """Create a new loadbalancer."""
    boot_args, boot_kwargs = _create(cs, args)

    #extra_boot_kwargs = utils.get_resource_manager_extra_kwargs(do_boot, args)
    #boot_kwargs.update(extra_boot_kwargs)

    loadbalancer = cs.loadbalancers.create(*boot_args, **boot_kwargs)

    # Keep any information (like adminPass) returned by create
    info = loadbalancer._info
    loadbalancer = cs.loadbalancers.get(info['id'])
    info.update(loadbalancer._info)

    #info.pop('links', None)
    info.pop('sourceAddresses', None)

    utils.print_dict(info)

    if args.poll:
        _poll_for_status(cs.loadbalancers.get, info['id'], 'building', ['active'])


def _poll_for_status(poll_fn, obj_id, action, final_ok_states,
                     poll_period=5, show_progress=True,
                     status_field="status", silent=False):
    """Block while an action is being performed, periodically printing
    progress.
    """
    def print_progress(progress):
        if show_progress:
            msg = ('\rInstance %(action)s... %(progress)s%% complete'
                   % dict(action=action, progress=progress))
        else:
            msg = '\rInstance %(action)s...' % dict(action=action)

        sys.stdout.write(msg)
        sys.stdout.flush()

    if not silent:
        print

    while True:
        obj = poll_fn(obj_id)

        status = getattr(obj, status_field)

        if status:
            status = status.lower()

        progress = getattr(obj, 'progress', None) or 0
        if status in final_ok_states:
            if not silent:
                print_progress(100)
                print("\nFinished")
            break
        elif status == "error":
            if not silent:
                print("\nError %s instance" % action)
            break

        if not silent:
            print_progress(progress)

        time.sleep(poll_period)


def _translate_keys(collection, convert):
    for item in collection:
        keys = item.__dict__.keys()
        for from_key, to_key in convert:
            if from_key in keys and to_key not in keys:
                setattr(item, to_key, item._info[from_key])


@utils.arg('project_id', metavar='<project_id>',
           help='The ID of the project.')
def do_scrub(cs, args):
    """Delete data associated with the project."""
    networks_list = cs.networks.list()
    networks_list = [network for network in networks_list
                 if getattr(network, 'project_id', '') == args.project_id]
    search_opts = {'all_tenants': 1}
    groups = cs.security_groups.list(search_opts)
    groups = [group for group in groups
              if group.tenant_id == args.project_id]
    for network in networks_list:
        cs.networks.disassociate(network)
    for group in groups:
        cs.security_groups.delete(group)


def _extract_metadata(args):
    metadata = {}
    for metadatum in args.metadata[0]:
        # Can only pass the key in on 'delete'
        # So this doesn't have to have '='
        if metadatum.find('=') > -1:
            (key, value) = metadatum.split('=', 1)
        else:
            key = metadatum
            value = None

        metadata[key] = value
    return metadata


@utils.arg('--name',
    dest='name',
    metavar='<name-regexp>',
    default=None,
    help='Search with regular expression match by name')
@utils.arg('--all-tenants',
    dest='all_tenants',
    metavar='<0|1>',
    nargs='?',
    type=int,
    const=1,
    default=int(utils.bool_from_str(os.environ.get("ALL_TENANTS", 'false'))),
    help='Display information from all tenants (Admin only).')
@utils.arg('--all_tenants',
    nargs='?',
    type=int,
    const=1,
    help=argparse.SUPPRESS)
@utils.arg('--tenant',
    #nova db searches by project_id
    dest='tenant',
    metavar='<tenant>',
    nargs='?',
    help='Display information from single tenant (Admin only).')
@utils.arg('--fields',
    default=None,
    metavar='<fields>',
    help='Comma-separated list of fields to display. '
         'Use the show command to see which fields are available.')
def do_list(cs, args):
    """List active loadbalancers."""
    def vip_filter(lb):
        vips = [x['address'] for x in lb.virtualIps]
        return ', '.join(vips)
    filters = {}
    formatters = {"VirtualIPs": vip_filter}
    field_titles = []
    if args.fields:
        for field in args.fields.split(','):
            field_title, formatter = utils._make_field_formatter(field,
                                                                 filters)
            field_titles.append(field_title)
            formatters[field_title] = formatter
    id_col = 'ID'

    loadbalancers = cs.loadbalancers.list()
    convert = [('OS-EXT-SRV-ATTR:host', 'host'),
               ('hostId', 'host_id')]
    _translate_keys(loadbalancers, convert)

    if field_titles:
        columns = [id_col] + field_titles
    else:
        columns = [
            id_col,
            'Name',
            'Status',
            'Protocol',
            'Port',
            'Algorithm',
            'VirtualIPs'
        ]
    utils.print_list(loadbalancers, columns,
                     formatters, sortby_index=1)


def _print_server(cs, args):
    # By default when searching via name we will do a
    # findall(name=blah) and due a REST /details which is not the same
    # as a .get() and doesn't get the information about flavors and
    # images. This fix it as we redo the call with the id which does a
    # .get() to get all informations.
    server = _find_server(cs, args.server)

    networks = server.networks
    info = server._info.copy()
    #print(info)
    for network_label, address_list in networks.items():
        info['%s network' % network_label] = ', '.join(address_list)

    info.pop('links', None)
    info.pop('sourceAddresses', None)

    utils.print_dict(info)


@utils.arg('server', metavar='<server>', help='Name or ID of server.')
def do_show(cs, args):
    """Show details about the given server."""
    _print_server(cs, args)


@utils.arg('server', metavar='<server>', nargs='+',
           help='Name or ID of server(s).')
def do_delete(cs, args):
    """Immediately shut down and delete specified server(s)."""
    failure_count = 0

    for server in args.server:
        try:
            _find_server(cs, server).delete()
        except Exception as e:
            failure_count += 1
            print(e)

    if failure_count == len(args.server):
        raise exceptions.CommandError("Unable to delete any of the specified "
                                      "loadbalancers.")


def _find_server(cs, server):
    """Get a server by name or ID."""
    return utils.find_resource(cs.loadbalancers, server)


@utils.arg('--tenant',
           #nova db searches by project_id
           dest='tenant',
           metavar='<tenant>',
           nargs='?',
           help='Display information from single tenant (Admin only).')
@utils.arg('--reserved',
           dest='reserved',
           action='store_true',
           default=False,
           help='Include reservations count.')
def do_absolute_limits(cs, args):
    """Print a list of absolute limits for a user"""
    limits = cs.limits.get(args.reserved, args.tenant).absolute
    columns = ['Name', 'Value']
    utils.print_list(limits, columns)


def do_rate_limits(cs, args):
    """Print a list of rate limits for a user"""
    limits = cs.limits.get().rate
    columns = ['Verb', 'URI', 'Value', 'Remain', 'Unit', 'Next_Available']
    utils.print_list(limits, columns)


@utils.arg('--start', metavar='<start>',
           help='Usage range start date ex 2012-01-20 (default: 4 weeks ago)',
           default=None)
@utils.arg('--end', metavar='<end>',
           help='Usage range end date, ex 2012-01-20 (default: tomorrow) ',
           default=None)
def do_usage_list(cs, args):
    """List usage data for all tenants."""
    dateformat = "%Y-%m-%d"
    rows = ["Tenant ID", "Instances", "RAM MB-Hours", "CPU Hours",
            "Disk GB-Hours"]

    now = timeutils.utcnow()

    if args.start:
        start = datetime.datetime.strptime(args.start, dateformat)
    else:
        start = now - datetime.timedelta(weeks=4)

    if args.end:
        end = datetime.datetime.strptime(args.end, dateformat)
    else:
        end = now + datetime.timedelta(days=1)

    def simplify_usage(u):
        simplerows = [x.lower().replace(" ", "_") for x in rows]

        setattr(u, simplerows[0], u.tenant_id)
        setattr(u, simplerows[1], "%d" % len(u.server_usages))
        setattr(u, simplerows[2], "%.2f" % u.total_memory_mb_usage)
        setattr(u, simplerows[3], "%.2f" % u.total_vcpus_usage)
        setattr(u, simplerows[4], "%.2f" % u.total_local_gb_usage)

    usage_list = cs.usage.list(start, end, detailed=True)

    print("Usage from %s to %s:" % (start.strftime(dateformat),
                                    end.strftime(dateformat)))

    for usage in usage_list:
        simplify_usage(usage)

    utils.print_list(usage_list, rows)


@utils.arg('--start', metavar='<start>',
           help='Usage range start date ex 2012-01-20 (default: 4 weeks ago)',
           default=None)
@utils.arg('--end', metavar='<end>',
           help='Usage range end date, ex 2012-01-20 (default: tomorrow) ',
           default=None)
@utils.arg('--tenant', metavar='<tenant-id>',
           default=None,
           help='UUID or name of tenant to get usage for.')
def do_usage(cs, args):
    """Show usage data for a single tenant."""
    dateformat = "%Y-%m-%d"
    rows = ["Instances", "RAM MB-Hours", "CPU Hours", "Disk GB-Hours"]

    now = timeutils.utcnow()

    if args.start:
        start = datetime.datetime.strptime(args.start, dateformat)
    else:
        start = now - datetime.timedelta(weeks=4)

    if args.end:
        end = datetime.datetime.strptime(args.end, dateformat)
    else:
        end = now + datetime.timedelta(days=1)

    def simplify_usage(u):
        simplerows = [x.lower().replace(" ", "_") for x in rows]

        setattr(u, simplerows[0], "%d" % len(u.server_usages))
        setattr(u, simplerows[1], "%.2f" % u.total_memory_mb_usage)
        setattr(u, simplerows[2], "%.2f" % u.total_vcpus_usage)
        setattr(u, simplerows[3], "%.2f" % u.total_local_gb_usage)

    if args.tenant:
        usage = cs.usage.get(args.tenant, start, end)
    else:
        usage = cs.usage.get(cs.client.tenant_id, start, end)

    print("Usage from %s to %s:" % (start.strftime(dateformat),
                                    end.strftime(dateformat)))

    if getattr(usage, 'total_vcpus_usage', None):
        simplify_usage(usage)
        utils.print_list([usage], rows)
    else:
        print('None')


@utils.arg('pk_filename',
    metavar='<private-key-filename>',
    nargs='?',
    default='pk.pem',
    help='Filename for the private key [Default: pk.pem]')
@utils.arg('cert_filename',
    metavar='<x509-cert-filename>',
    nargs='?',
    default='cert.pem',
    help='Filename for the X.509 certificate [Default: cert.pem]')
def do_x509_create_cert(cs, args):
    """Create x509 cert for a user in tenant."""

    if os.path.exists(args.pk_filename):
        raise exceptions.CommandError("Unable to write privatekey - %s exists."
                        % args.pk_filename)
    if os.path.exists(args.cert_filename):
        raise exceptions.CommandError("Unable to write x509 cert - %s exists."
                        % args.cert_filename)

    certs = cs.certs.create()

    try:
        old_umask = os.umask(0o377)
        with open(args.pk_filename, 'w') as private_key:
            private_key.write(certs.private_key)
            print("Wrote private key to %s" % args.pk_filename)
    finally:
        os.umask(old_umask)

    with open(args.cert_filename, 'w') as cert:
        cert.write(certs.data)
        print("Wrote x509 certificate to %s" % args.cert_filename)


@utils.arg('filename',
           metavar='<filename>',
           nargs='?',
           default='cacert.pem',
           help='Filename to write the x509 root cert.')
def do_x509_get_root_cert(cs, args):
    """Fetch the x509 root cert."""
    if os.path.exists(args.filename):
        raise exceptions.CommandError("Unable to write x509 root cert - \
                                      %s exists." % args.filename)

    with open(args.filename, 'w') as cert:
        cacert = cs.certs.get()
        cert.write(cacert.data)
        print("Wrote x509 root cert to %s" % args.filename)


def ensure_service_catalog_present(cs):
    if not hasattr(cs.client, 'service_catalog'):
        # Turn off token caching and re-auth
        cs.client.unauthenticate()
        cs.client.use_token_cache(False)
        cs.client.authenticate()


def do_endpoints(cs, _args):
    """Discover endpoints that get returned from the authenticate services."""
    ensure_service_catalog_present(cs)
    catalog = cs.client.service_catalog.catalog
    for e in catalog['access']['serviceCatalog']:
        utils.print_dict(e['endpoints'][0], e['name'])


@utils.arg('--wrap', dest='wrap', metavar='<integer>', default=64,
           help='wrap PKI tokens to a specified length, or 0 to disable')
def do_credentials(cs, _args):
    """Show user credentials returned from auth."""
    ensure_service_catalog_present(cs)
    catalog = cs.client.service_catalog.catalog
    utils.print_dict(catalog['access']['user'], "User Credentials",
                     wrap=int(_args.wrap))
    utils.print_dict(catalog['access']['token'], "Token", wrap=int(_args.wrap))


_quota_resources = ['instances', 'cores', 'ram', 'volumes', 'gigabytes',
                    'floating_ips', 'fixed_ips', 'metadata_items',
                    'injected_files', 'injected_file_content_bytes',
                    'injected_file_path_bytes', 'key_pairs',
                    'security_groups', 'security_group_rules']


def _quota_show(quotas):
    class FormattedQuota(object):
        def __init__(self, key, value):
            setattr(self, 'quota', key)
            setattr(self, 'limit', value)

    quota_list = []
    for resource in _quota_resources:
        try:
            quota = FormattedQuota(resource, getattr(quotas, resource))
            quota_list.append(quota)
        except AttributeError:
            pass
    columns = ['Quota', 'Limit']
    utils.print_list(quota_list, columns)


def _quota_update(manager, identifier, args):
    updates = {}
    for resource in _quota_resources:
        val = getattr(args, resource, None)
        if val is not None:
            updates[resource] = val

    if updates:
        # default value of force is None to make sure this client
        # will be compatibile with old nova server
        force_update = getattr(args, 'force', None)
        user_id = getattr(args, 'user', None)
        if isinstance(manager, quotas.QuotaSetManager):
            manager.update(identifier, force=force_update, user_id=user_id,
                           **updates)
        else:
            manager.update(identifier, **updates)


@utils.arg('--tenant',
    metavar='<tenant-id>',
    default=None,
    help='ID of tenant to list the quotas for.')
@utils.arg('--user',
    metavar='<user-id>',
    default=None,
    help='ID of user to list the quotas for.')
def do_quota_show(cs, args):
    """List the quotas for a tenant/user."""

    if not args.tenant:
        _quota_show(cs.quotas.get(cs.client.tenant_id, user_id=args.user))
    else:
        _quota_show(cs.quotas.get(args.tenant, user_id=args.user))


@utils.arg('--tenant',
    metavar='<tenant-id>',
    default=None,
    help='ID of tenant to list the default quotas for.')
def do_quota_defaults(cs, args):
    """List the default quotas for a tenant."""

    if not args.tenant:
        _quota_show(cs.quotas.defaults(cs.client.tenant_id))
    else:
        _quota_show(cs.quotas.defaults(args.tenant))


@utils.arg('tenant',
    metavar='<tenant-id>',
    help='ID of tenant to set the quotas for.')
@utils.arg('--user',
           metavar='<user-id>',
           default=None,
           help='ID of user to set the quotas for.')
@utils.arg('--instances',
           metavar='<instances>',
           type=int, default=None,
           help='New value for the "instances" quota.')
@utils.arg('--cores',
           metavar='<cores>',
           type=int, default=None,
           help='New value for the "cores" quota.')
@utils.arg('--ram',
           metavar='<ram>',
           type=int, default=None,
           help='New value for the "ram" quota.')
@utils.arg('--volumes',
           metavar='<volumes>',
           type=int, default=None,
           help='New value for the "volumes" quota.')
@utils.arg('--gigabytes',
           metavar='<gigabytes>',
           type=int, default=None,
           help='New value for the "gigabytes" quota.')
@utils.arg('--floating-ips',
    metavar='<floating-ips>',
    type=int,
    default=None,
    help='New value for the "floating-ips" quota.')
@utils.arg('--floating_ips',
    type=int,
    help=argparse.SUPPRESS)
@utils.arg('--fixed-ips',
    metavar='<fixed-ips>',
    type=int,
    default=None,
    help='New value for the "fixed-ips" quota.')
@utils.arg('--metadata-items',
    metavar='<metadata-items>',
    type=int,
    default=None,
    help='New value for the "metadata-items" quota.')
@utils.arg('--metadata_items',
    type=int,
    help=argparse.SUPPRESS)
@utils.arg('--injected-files',
    metavar='<injected-files>',
    type=int,
    default=None,
    help='New value for the "injected-files" quota.')
@utils.arg('--injected_files',
    type=int,
    help=argparse.SUPPRESS)
@utils.arg('--injected-file-content-bytes',
    metavar='<injected-file-content-bytes>',
    type=int,
    default=None,
    help='New value for the "injected-file-content-bytes" quota.')
@utils.arg('--injected_file_content_bytes',
    type=int,
    help=argparse.SUPPRESS)
@utils.arg('--injected-file-path-bytes',
    metavar='<injected-file-path-bytes>',
    type=int,
    default=None,
    help='New value for the "injected-file-path-bytes" quota.')
@utils.arg('--key-pairs',
    metavar='<key-pairs>',
    type=int,
    default=None,
    help='New value for the "key-pairs" quota.')
@utils.arg('--security-groups',
    metavar='<security-groups>',
    type=int,
    default=None,
    help='New value for the "security-groups" quota.')
@utils.arg('--security-group-rules',
    metavar='<security-group-rules>',
    type=int,
    default=None,
    help='New value for the "security-group-rules" quota.')
@utils.arg('--force',
    dest='force',
    action="store_true",
    default=None,
    help='Whether force update the quota even if the already used'
            ' and reserved exceeds the new quota')
def do_quota_update(cs, args):
    """Update the quotas for a tenant/user."""

    _quota_update(cs.quotas, args.tenant, args)


@utils.arg('--tenant',
           metavar='<tenant-id>',
           help='ID of tenant to delete quota for.')
@utils.arg('--user',
           metavar='<user-id>',
           help='ID of user to delete quota for.')
def do_quota_delete(cs, args):
    """Delete quota for a tenant/user so their quota will Revert
       back to default.
    """

    cs.quotas.delete(args.tenant, user_id=args.user)


@utils.arg('class_name',
    metavar='<class>',
    help='Name of quota class to list the quotas for.')
def do_quota_class_show(cs, args):
    """List the quotas for a quota class."""

    _quota_show(cs.quota_classes.get(args.class_name))


@utils.arg('class_name',
    metavar='<class>',
    help='Name of quota class to set the quotas for.')
@utils.arg('--instances',
           metavar='<instances>',
           type=int, default=None,
           help='New value for the "instances" quota.')
@utils.arg('--cores',
           metavar='<cores>',
           type=int, default=None,
           help='New value for the "cores" quota.')
@utils.arg('--ram',
           metavar='<ram>',
           type=int, default=None,
           help='New value for the "ram" quota.')
@utils.arg('--volumes',
           metavar='<volumes>',
           type=int, default=None,
           help='New value for the "volumes" quota.')
@utils.arg('--gigabytes',
           metavar='<gigabytes>',
           type=int, default=None,
           help='New value for the "gigabytes" quota.')
@utils.arg('--floating-ips',
    metavar='<floating-ips>',
    type=int,
    default=None,
    help='New value for the "floating-ips" quota.')
@utils.arg('--floating_ips',
    type=int,
    help=argparse.SUPPRESS)
@utils.arg('--metadata-items',
    metavar='<metadata-items>',
    type=int,
    default=None,
    help='New value for the "metadata-items" quota.')
@utils.arg('--metadata_items',
    type=int,
    help=argparse.SUPPRESS)
@utils.arg('--injected-files',
    metavar='<injected-files>',
    type=int,
    default=None,
    help='New value for the "injected-files" quota.')
@utils.arg('--injected_files',
    type=int,
    help=argparse.SUPPRESS)
@utils.arg('--injected-file-content-bytes',
    metavar='<injected-file-content-bytes>',
    type=int,
    default=None,
    help='New value for the "injected-file-content-bytes" quota.')
@utils.arg('--injected_file_content_bytes',
    type=int,
    help=argparse.SUPPRESS)
@utils.arg('--injected-file-path-bytes',
    metavar='<injected-file-path-bytes>',
    type=int,
    default=None,
    help='New value for the "injected-file-path-bytes" quota.')
@utils.arg('--key-pairs',
    metavar='<key-pairs>',
    type=int,
    default=None,
    help='New value for the "key-pairs" quota.')
@utils.arg('--security-groups',
    metavar='<security-groups>',
    type=int,
    default=None,
    help='New value for the "security-groups" quota.')
@utils.arg('--security-group-rules',
    metavar='<security-group-rules>',
    type=int,
    default=None,
    help='New value for the "security-group-rules" quota.')
def do_quota_class_update(cs, args):
    """Update the quotas for a quota class."""

    _quota_update(cs.quota_classes, args.class_name, args)

