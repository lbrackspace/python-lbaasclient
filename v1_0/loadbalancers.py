# Copyright 2010 Jacob Kaplan-Moss

# Copyright 2011 OpenStack Foundation
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

"""
Loadbalancer interface.
"""

import six

from lbaasclient import base
from lbaasclient import crypto
from lbaasclient.openstack.common.py3kcompat import urlutils
from lbaasclient.v1_0.security_groups import SecurityGroup


class Loadbalancer(base.Resource):
    HUMAN_ID = True

    def __repr__(self):
        return "<Loadbalancer: %s>" % self.name

    def delete(self):
        """
        Delete (i.e. shut down and delete the image) this loadbalancer.
        """
        self.manager.delete(self)

    def update(self, name=None):
        """
        Update the name or the password for this loadbalancer.

        :param name: Update the loadbalancer's name.
        :param password: Update the root password.
        """
        self.manager.update(self, name=name)

    @property
    def networks(self):
        """
        Generate a simplified list of addresses
        """
        networks = {}
        try:
            for network_label, address_list in self.addresses.items():
                networks[network_label] = [a['addr'] for a in address_list]
            return networks
        except Exception:
            return {}


class LoadbalancerManager(base.BootingManagerWithFind):
    resource_class = Loadbalancer

    def get(self, loadbalancer):
        """
        Get a loadbalancer.

        :param loadbalancer: ID of the :class:`Loadbalancer` to get.
        :rtype: :class:`Loadbalancer`
        """
        return self._get("/loadbalancers/%s" % base.getid(loadbalancer), "loadBalancer")

    def list(self, detailed=True, search_opts=None, marker=None, limit=None):
        """
        Get a list of loadbalancers.

        :param detailed: Whether to return detailed loadbalancer info (optional).
        :param search_opts: Search options to filter out loadbalancers (optional).
        :param marker: Begin returning loadbalancers that appear later in the loadbalancer
                       list than that represented by this loadbalancer id (optional).
        :param limit: Maximum number of loadbalancers to return (optional).

        :rtype: list of :class:`Loadbalancer`
        """
        if search_opts is None:
            search_opts = {}

        qparams = {}

        for opt, val in six.iteritems(search_opts):
            if val:
                qparams[opt] = val

        if marker:
            qparams['marker'] = marker

        if limit:
            qparams['limit'] = limit

        query_string = "?%s" % urlutils.urlencode(qparams) if qparams else ""

        return self._list("/loadbalancers%s" % (query_string,), "loadBalancers")

    def create(self, name, protocol, vip_type, port=None, algorithm=None,
               nodes=None, **kwargs):
        # TODO(anthony): indicate in doc string if param is an extension
        # and/or optional
        """
        Create (boot) a new loadbalancer.

        :param name: Something to name the loadbalancer.
        :param protocol: The :class:`Image` to boot with.
        :param vip_type: The :class:`Flavor` to boot onto.
        """
        boot_args = [name, protocol, vip_type]

        boot_kwargs = dict(
            port=port, algorithm=algorithm, nodes=nodes, **kwargs)

        resource_url = "/loadbalancers"
        response_key = "loadBalancer"
        return self._do_create(resource_url, response_key, *boot_args,
                **boot_kwargs)

    def update(self, loadbalancer, name=None):
        """
        Update the name or the password for a loadbalancer.

        :param loadbalancer: The :class:`Loadbalancer` (or its ID) to update.
        :param name: Update the loadbalancer's name.
        """
        if name is None:
            return

        body = {
            "loadbalancer": {
                "name": name,
            },
        }

        return self._update("/loadbalancers/%s" % base.getid(loadbalancer), body, "loadbalancer")

    def delete(self, loadbalancer):
        """
        Delete (i.e. shut down and delete the image) this loadbalancer.
        """
        self._delete("/loadbalancers/%s" % base.getid(loadbalancer))

    def _action(self, action, loadbalancer, info=None, **kwargs):
        """
        Perform a loadbalancer "action" -- reboot/rebuild/resize/etc.
        """
        body = {action: info}
        self.run_hooks('modify_body_for_action', body, **kwargs)
        url = '/loadbalancers/%s/action' % base.getid(loadbalancer)
        return self.api.client.post(url, body=body)
