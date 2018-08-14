import logging

import shade

import padre.date_utils as du

LOG = logging.getLogger(__name__)

CLOUDS = tuple([
    ":cloud:",
    ":rain_cloud:",
    ":sun_small_cloud:",
    ":rainbow-cloud:",
])


def iter_ips_of_type(server, desired_ip_type):
    all_addrs = server.get("addresses", {})
    for _addr_net, addrs in all_addrs.items():
        for addr in addrs:
            ip = addr.get("addr")
            ip_type = addr.get("OS-EXT-IPS:type")
            if ip and ip_type == desired_ip_type:
                yield ip


def disable_scheduling(topo, hypervisors, change_number='Unknown',
                       task_number='Unknown', reason=None,
                       when_disabled=du.get_now()):
    """Disables scheduling on the provided hypervisors.

    Iterates over all provided hypervisors and disables them.
    :param topo: A topology to use for disabling
    :param hypervisors: A iterable collection of hypervisor fqdns.
    :param change_number: The change this tied to (default Unknown)
    :param task_number: The task this was done for (default Unknown)
    :param reason: A short reason why this is being disabled.
    :param when_disabled: Datetime when this disabling occurred (default now)
    :return: A tuple with list of successes, failed, last exception
    """
    succeeded = []
    failed = []
    error = None

    # Sanity checks
    if not hypervisors:
        return succeeded, failed, \
            'Attempted disable hypervisors for scheduling without ' \
            'providing a collection of hypervisors to match. Skipping.'
    if not topo:
        return succeeded, failed, \
            'Attempted disable hypervisor for scheduling without ' \
            'providing a valid cloud topo. Skipping.'

    # Get a list of all compute services for this cloud
    config = topo.render('os_client_config')
    cloud_config = config.get_one_cloud(cloud=topo.cloud.canonical_name)
    cloud = shade.OpenStackCloud(cloud_config=cloud_config)
    nova_client = cloud.nova_client
    services = nova_client.services.list(binary="nova-compute")

    # Find common list between services and provided hvs (not already disabled)
    hv_set = set(hypervisors)
    matched_services = []
    for service in services:
        if service.host in hv_set and service.status == 'enabled':
            matched_services.append(service)
    if not matched_services:
        return succeeded, failed, \
            'Did not find any enabled HVs to disable. skipping.'

    # Disable the services.
    reason = "Disabled on %s via automation for change (%s), ctask(%s) " \
             "for reason: %s" % (when_disabled.strftime('%Y-%m-%d'),
                                 change_number, task_number,
                                 reason or 'No reason provided')
    for service in matched_services:
        try:
            nova_client.services.disable_log_reason(
                service.host, 'nova-compute', reason=reason)
            succeeded.append(service.host)
        except Exception as ex:
            LOG.exception('Exception while disabling host scheduling')
            failed.append(service.host)
            error = ex.message

    return succeeded, failed, error


def enable_scheduling(topo, change_number=None):
    """Enables scheduling on hypervisors whose reason includes change_number.

    Iterates over all disabled hosts and re-enables them when the provided
    change number text is in the disabled_reason field.
    :param topo: The topology for the cloud we're scheduling for.
    :param change_number: The change number to re-enable for.
    :return: A tuple with list of successes, failed, last exception
    """
    succeeded = []
    failed = []
    error = None
    if not topo:
        return succeeded, failed, \
            'Attempted re-enable hypervisors for scheduling without ' \
            'providing a valid topology. Bailing out. Fix it!'

    # Get a list of all compute services for this cloud
    config = topo.render('os_client_config')
    cloud_config = config.get_one_cloud(cloud=topo.cloud.canonical_name)
    cloud = shade.OpenStackCloud(cloud_config=cloud_config)
    nova_client = cloud.nova_client
    services = nova_client.services.list(binary="nova-compute")

    # Find all disabled hosts that have our change_number text
    matched_services = []
    for service in services:
        if service.status == 'disabled' and service.disabled_reason and \
                change_number in service.disabled_reason:
            matched_services.append(service)
    if not matched_services:
        return succeeded, failed, \
            'Did not find any disabled HVs to re-enable. skipping.'

    # Re-enable the services.
    for service in matched_services:
        try:
            nova_client.services.enable(service.host, 'nova-compute')
            succeeded.append(service.host)
        except Exception as ex:
            error = ex.message
            failed.append(service.host)

    return succeeded, failed, error
