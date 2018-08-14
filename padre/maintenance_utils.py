import json
import logging
import pytz
import re
import urllib

import enum
import munch
import pysnow
import requests
import six

from padre import utils

LOG = logging.getLogger(__name__)
DEFAULT_OUT_HEADERS = {
    'Content-Type': 'application/json',
    'Accept-Type': 'application/json',
}
DEFAULT_DT_FORMAT = '%Y-%m-%d %H:%M:%S'


def _inject_return_fields(url_params, return_fields=None):
    if return_fields is not None:
        if isinstance(return_fields, (set, list, tuple)):
            return_fields = ",".join(sorted(return_fields))
        if not isinstance(return_fields, six.string_types):
            raise TypeError("Return fields (aka `sysparm_fields`) must"
                            " be a set/list/tuple"
                            " or string type (and not"
                            " %s)" % type(return_fields))
        url_params['sysparm_fields'] = return_fields


def clean_user_keys(data, recurse=False):
    n_data = data.copy()
    for k, v in six.iteritems(data):
        if k.startswith("u_"):
            n_data.pop(k)
        elif isinstance(v, dict) and recurse:
            n_data[k] = clean_user_keys(v, recurse=recurse)
    return n_data


def extract_server_owning_groups(servers):
    groups = []
    missing_groups = 0
    for s in servers:
        s_owner = None
        try:
            s_owner = s.metadata.owning_group
            # remove prefix numbers
            s_owner = re.sub('^\d+\s+-\s', '', s_owner)
        except AttributeError:
            pass
        if s_owner and s_owner not in groups:
            groups.append(s_owner)
        if not s_owner:
            missing_groups += 1
    return groups, missing_groups


def snow_date(date):
    new_date = date.astimezone(pytz.utc)
    return new_date.strftime(DEFAULT_DT_FORMAT)


class InstallStatus(enum.Enum):
    UNKNOWN = -1024
    IN_STOCK = 6
    INSTALLED = 1
    ON_ORDER = 2
    PENDING_INSTALL = 4
    PENDING_REPAIR = 5
    RETIRED = 7
    STOLEN = 8
    LIVE = INSTALLED

    @classmethod
    def convert(cls, val):
        m_state = cls.UNKNOWN
        tmp_val = int(val)
        for st in list(cls):
            if st.value == tmp_val:
                m_state = st
                break
        return m_state


class ChangeState(enum.Enum):
    UNKNOWN = -1024
    PENDING = -5
    OPEN = 1
    WIP = 2
    COMPLETE = 3
    INCOMPLETE = 4
    SKIPPED = 7

    @classmethod
    def convert(cls, val):
        m_state = cls.UNKNOWN
        tmp_val = int(val)
        for st in list(cls):
            if st.value == tmp_val:
                m_state = st
                break
        return m_state


class ServiceNow(object):
    # TODO: For a time we are using the REST calls directly, we need to
    # fix this just to use the snow/servicenow library at a point...
    endpoint_tpl = 'https://%(env)s.service-now.com'
    endpoint_tables = (
        'change_request',
        'change_task',
        'cmdb_ci',
        'incident',
        'problem',
        'sc_req_item',
        'sc_request',
        'sys_user_group',
    )

    def __init__(self, environment, user, password, timeout=None):
        self.auth = (user, password)
        self.table_endpoints = {}
        self.endpoint = self.endpoint_tpl % {
            'env': environment,
        }
        self.timeout = timeout
        for table in self.endpoint_tables:
            table_url = self.endpoint
            table_url += "/api/now/table/"
            table_url += urllib.quote(table)
            self.table_endpoints[table] = table_url
        self.misc_endpoints = {
            "on_call_current": ("%s/api/now/on_call_rota"
                                "/current" % self.endpoint),
            "bulk_cis": ("%s/task_ci.do?JSONv2&sysparm_action=insertMultiple"
                         % self.endpoint),
        }

    def _make_human_link(self, item):
        item_sys_class_name = item.get("sys_class_name")
        item_sys_id = item.get("sys_id")
        if not all([item_sys_class_name, item_sys_id]):
            return None
        item_uri = "/%s.do?" % urllib.quote(item_sys_class_name)
        item_uri += urllib.urlencode({
            'sys_id': item_sys_id,
            'sysparm_record_target': item_sys_class_name,
        })
        link = self.endpoint
        link += "/nav_to.do?"
        link += urllib.urlencode({
            'uri': item_uri,
        })
        return link

    def get_group(self, group_name, return_fields=(), timeout=None):
        if timeout is None:
            timeout = self.timeout
        url = self.table_endpoints['sys_user_group']
        url += "?"
        url_params = {
            'sysparm_limit': 1,
            'name': group_name,
        }
        _inject_return_fields(url_params, return_fields=return_fields)
        url += urllib.urlencode(url_params)
        resp = requests.get(url, headers=DEFAULT_OUT_HEADERS.copy(),
                            auth=self.auth, timeout=timeout)
        resp.raise_for_status()
        res = resp.json()
        res = res['result']
        if res:
            raw_group = res[0]
            return munch.munchify(raw_group)
        else:
            return None

    def list_groups(self, timeout=None):
        if timeout is None:
            timeout = self.timeout
        url = self.table_endpoints['sys_user_group']
        resp = requests.get(url, headers=DEFAULT_OUT_HEADERS.copy(),
                            auth=self.auth, timeout=timeout)
        resp.raise_for_status()
        res = resp.json()
        groups = []
        for raw_group in res['result']:
            groups.append(munch.munchify(raw_group))
        return groups

    def _extract_result_from_response(self, resp, url, partial_url=True):
        res = resp.json()
        res = munch.munchify(res['result'])
        # TODO: why isn't this included in the response???
        if 'link' not in res:
            if partial_url:
                res['link'] = resp.headers.get(
                    'location', url + "/" + res['sys_id'])
            else:
                res['link'] = resp.headers.get('location', url)
        return res

    def list_table(self, group, table='change_request', params=None,
                   timeout=None):
        if timeout is None:
            timeout = self.timeout
        url = self.table_endpoints[table]
        if params is None:
            params = {}
        if group is not None:
            if isinstance(group, munch.Munch):
                params['assignment_group'] = group.sys_id
            else:
                params['assignment_group'] = group
        if params:
            url += "?"
            url += urllib.urlencode(params)
        resp = requests.get(url, headers=DEFAULT_OUT_HEADERS.copy(),
                            auth=self.auth, timeout=timeout)
        res = resp.json()
        changes = []
        for chg in res['result']:
            chg = munch.munchify(chg)
            # NOTE: for some reason this isn't returned...
            chg_human_link = self._make_human_link(chg)
            if chg_human_link:
                chg['human_link'] = chg_human_link
            changes.append(chg)
        return changes

    def get_change_by_id(self, sys_id, return_fields=(), timeout=None):
        return self.get_by_id(sys_id, table='change_request',
                              return_fields=return_fields,
                              timeout=timeout)

    def get_ci_by_id(self, sys_id, return_fields=(), timeout=None):
        return self.get_by_id(sys_id, table='cmdb_ci',
                              return_fields=return_fields,
                              timeout=timeout)

    def find_cis(self, ip_address=None,
                 install_status=InstallStatus.LIVE,
                 category='Hardware', subcategory='Computer',
                 name=None, in_maintenance=None, limit=None,
                 return_fields=(), timeout=None):
        # TODO Should be able to filter by owning_group or support_group

        # For now, We need at least some name or ip so that we can limit the
        # search to 1 item, instead of a potential crap ton...
        # TODO Remove this when reasonable limit + return_fields smallish
        if ip_address is None and name is None:
            raise ValueError("At least one of 'name' or 'ip_address'"
                             " must be passed (otherwise we may find"
                             " way more than desired)")
        if timeout is None:
            timeout = self.timeout
        q_ands = []
        if name:
            q_ands.append(("name", str(name)))
        if ip_address is not None:
            q_ands.append(('ip_address', str(ip_address)))
        if (install_status is not None and
                install_status != InstallStatus.UNKNOWN):
            q_ands.append(('install_status', str(install_status.value)))
        if category:
            q_ands.append(("category", str(category)))
        if subcategory:
            q_ands.append(("subcategory", str(subcategory)))
        if in_maintenance:
            q_ands.append(('u_maintenance_status',
                           '1' if in_maintenance else '0'))
        q = pysnow.QueryBuilder()
        for i, (k, v) in enumerate(q_ands):
            q = q.field(k).equals(v)
            if i + 1 != len(q_ands):
                q = q.AND()
        url_params = {
            'sysparm_query': str(q),
        }
        if limit is not None:
            url_params['sysparm_limit'] = limit
        _inject_return_fields(url_params, return_fields=return_fields)
        url = self.table_endpoints['cmdb_ci']
        url += "?"
        url += urllib.urlencode(url_params)
        resp = requests.get(url, headers=DEFAULT_OUT_HEADERS.copy(),
                            auth=self.auth, timeout=timeout)
        resp.raise_for_status()
        res = resp.json()
        res = res['result']
        cis = []
        if res:
            for ci in res:
                ci = munch.munchify(ci)
                ci_human_link = self._make_human_link(ci)
                if ci_human_link:
                    ci['human_link'] = ci_human_link
                if 'u_maintenance_status' in ci:
                    # Convert status back into a bool
                    ci['u_maintenance_status'] = \
                        ci.u_maintenance_status in ['1', 1]
                cis.append(ci)
        return cis

    def find_ci(self, ip_address=None,
                install_status=InstallStatus.LIVE, category='Hardware',
                subcategory='Computer', name=None, in_maintenance=None,
                return_fields=(), timeout=None):
        cis = self.find_cis(ip_address=ip_address,
                            install_status=install_status,
                            category=category, subcategory=subcategory,
                            name=name, in_maintenance=in_maintenance, limit=1,
                            timeout=timeout, return_fields=return_fields)
        if cis:
            return cis[0]
        else:
            return None

    def update_ci(self, ci_sys_id, u_maintenance_status=None,
                  timeout=None):
        """Updates a CI record based on tha data provided

        :param ci_sys_id: the sys_id of item to be updated.
        :param u_maintenance_status: bool value whether this item is to be in
        maintenance mode
        :param timeout: How long to wait before timeout.
        :return: Result of the table update
        """
        data = {}
        if u_maintenance_status is not None:
            data['u_maintenance_status'] = 1 if u_maintenance_status else 0
        # TODO Update other CI fields? If so, which should we and why?
        # TODO Update returns ALL fields. Can we pass in return_fields?
        if data:
            return self._update(data, ci_sys_id, 'cmdb_ci', timeout=timeout)
        else:
            return None

    def get_by_id(self, sys_id, table='change_request',
                  return_fields=(), timeout=None):
        if timeout is None:
            timeout = self.timeout
        url = self.table_endpoints[table]
        url_params = {
            'sysparm_limit': 1,
            'sys_id': sys_id,
        }
        _inject_return_fields(url_params, return_fields=return_fields)
        url += "?"
        url += urllib.urlencode(url_params)
        resp = requests.get(url, headers=DEFAULT_OUT_HEADERS.copy(),
                            auth=self.auth, timeout=timeout)
        resp.raise_for_status()
        res = resp.json()
        res = res['result']
        if res:
            item = munch.munchify(res[0])
            item_human_link = self._make_human_link(item)
            if item_human_link:
                item['human_link'] = item_human_link
            return item
        else:
            return None

    def get_by_number(self, thing_number, table,
                      return_fields=(), timeout=None):
        if timeout is None:
            timeout = self.timeout
        url = self.table_endpoints[table]
        url += "?"
        url_params = {
            'sysparm_limit': 1,
            'number': str(thing_number),
        }
        _inject_return_fields(url_params, return_fields=return_fields)
        url += urllib.urlencode(url_params)
        resp = requests.get(url, headers=DEFAULT_OUT_HEADERS.copy(),
                            auth=self.auth, timeout=timeout)
        resp.raise_for_status()
        res = resp.json()
        res = res['result']
        if res:
            item = munch.munchify(res[0])
            item_human_link = self._make_human_link(item)
            if item_human_link:
                item['human_link'] = item_human_link
            return item
        else:
            return None

    def get_change(self, change_number, return_fields=(), timeout=None):
        return self.get_by_number(change_number, 'change_request',
                                  return_fields=return_fields,
                                  timeout=timeout)

    def find_on_call(self, group_name, timeout=None):
        if timeout is None:
            timeout = self.timeout
        url = self.misc_endpoints['on_call_current']
        url += "?"
        q = pysnow.QueryBuilder().field("group_name").equals(group_name)
        url += str(q)
        resp = requests.get(url, headers=DEFAULT_OUT_HEADERS.copy(),
                            auth=self.auth, timeout=timeout)
        resp.raise_for_status()
        res = resp.json()
        res = res['result']
        if res:
            on_call = []
            for u in res['users']:
                on_call_user = munch.Munch()
                for k, v in u.items():
                    k = utils.camel_to_underscore(k)
                    on_call_user[k] = v
                on_call.append(on_call_user)
            return on_call
        else:
            return None

    def create_change(self, short_description, description, change_plan,
                      assignment_group, start_date, end_date,
                      chg_type='Automated', timeout=None, downtime_minutes=60,
                      maintenance_cis=True, state=ChangeState.OPEN):
        """Creates a Service Now change request.

        :param short_description: Short description for this change
        :param description: Full description (short descif not provided)
        :param change_plan: The steps that will be taken.
        :param assignment_group: The group doing this change.
        :param start_date: The datetime when to start (must have tz).
        :param end_date: The datetime when to be complete (must have tz).
        :param chg_type: Type of change (Manual or default Automated)
        :param timeout: Timeout for this creation (seconds).
        :param downtime_minutes: Expected downtime for customers.
        :param maintenance_cis: (bool) Whether should put CIs in maintenance
        defaults True).
        :param state: The target state on creation (default ChangeState.OPEN)
        :return: Result from the creation.
        """
        if timeout is None:
            timeout = self.timeout
        data = {
            'assignment_group': assignment_group,
            'short_description': short_description,
            'type': chg_type,
            'description': description,
            'change_plan': change_plan,
            'start_date': snow_date(start_date),
            'end_date': snow_date(end_date),
            # flag indicating this CHG should maintenance CIs
            'u_maintenance_ci': str(maintenance_cis).lower(),
            'u_estimated_downtime': downtime_minutes,
            'state': state.value,
        }
        url = self.table_endpoints['change_request']
        resp = requests.post(url, headers=DEFAULT_OUT_HEADERS.copy(),
                             data=json.dumps(data), auth=self.auth,
                             timeout=timeout)
        resp.raise_for_status()
        chg = self._extract_result_from_response(resp, url)
        chg_human_link = self._make_human_link(chg)
        if chg_human_link:
            chg['human_link'] = chg_human_link
        return chg

    def add_bulk_cis(self, change_order_sys_id, ci_assets, timeout=None):
        """Adds CIs to a change request.

        Note: This method assumes a valid change_order_sys_id and upper-cased
        CI shortnames. Please feed this beast correctly. Derived from the doc
        posted here:
        :param change_order_sys_id: The sys_id of the change order to target.
        :param ci_assets: The non-empty list of upper-cased server shortnames
        :param timeout: How long to wait before this times out.
        :return: json parsed response information.
        """
        url = self.misc_endpoints['bulk_cis']

        # Build body for the bulk request
        ci_req_list = []
        for ci in ci_assets:
            ci_req_list.append(dict(ci_item=ci, task=change_order_sys_id))
        data = {'records': ci_req_list}

        # Post the bulk CI adds
        resp = requests.post(url, headers=DEFAULT_OUT_HEADERS.copy(),
                             data=json.dumps(data), auth=self.auth,
                             timeout=timeout)
        resp.raise_for_status()
        return munch.munchify(resp.json())

    def _update(self, data, sys_id, table, timeout=None):
        if timeout is None:
            timeout = self.timeout
        url = self.table_endpoints[table]
        url += "/"
        url += urllib.quote(sys_id)
        resp = requests.put(url, headers=DEFAULT_OUT_HEADERS.copy(),
                            auth=self.auth, data=json.dumps(data),
                            timeout=timeout)
        resp.raise_for_status()
        res = resp.json()
        res = res['result']
        if res:
            item = munch.munchify(res)
            item_human_link = self._make_human_link(item)
            if item_human_link:
                item['human_link'] = item_human_link
            return item
        else:
            return None

    def update_ctask(self, ctask_sys_id, planned_start_date=None,
                     state=None, timeout=None):
        data = {}
        if state is not None:
            data['state'] = str(state.value)
        if planned_start_date is not None:
            if not isinstance(planned_start_date, six.string_types):
                planned_start_date = planned_start_date.strftime(
                    DEFAULT_DT_FORMAT)
            data['planned_start_date'] = planned_start_date
        return self._update(data, ctask_sys_id,
                            'change_task', timeout=timeout)

    def update_change(self, change_sys_id, status=None,
                      start_date=None, end_date=None,
                      work_notes=None, timeout=None,
                      state=None):
        data = {}
        if status is not None:
            data['status'] = str(status.value)
        if start_date is not None:
            if not isinstance(start_date, six.string_types):
                start_date = start_date.strftime(DEFAULT_DT_FORMAT)
            data['start_date'] = start_date
        if end_date is not None:
            if not isinstance(end_date, six.string_types):
                end_date = end_date.strftime(DEFAULT_DT_FORMAT)
            data['end_date'] = end_date
        if work_notes is not None:
            data['work_notes'] = str(work_notes)
        if state is not None:
            data['state'] = str(state.value)
        return self._update(data, change_sys_id,
                            'change_request', timeout=timeout)

    def close_change(self, change_sys_id, state=ChangeState.COMPLETE,
                     timeout=None):
        return self.update_change(change_sys_id,
                                  state=state, timeout=timeout)
