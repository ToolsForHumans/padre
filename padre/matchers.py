from padre import message


def _make_matcher(base_component, sub_components):

    def _matcher(m, h_cls, only_to_me=True):
        if m.kind != base_component:
            return False
        m_sub_components = m.sub_kind.split("/")
        tmp_sub_components = list(sub_components)
        while m_sub_components and tmp_sub_components:
            k_c = m_sub_components.pop(0)
            s_c = tmp_sub_components.pop(0)
            if k_c != s_c:
                return False
        if tmp_sub_components:
            return False
        to_me = m.headers.get(message.TO_ME_HEADER, False)
        if only_to_me and not to_me:
            return False
        direct_h_cls = m.headers.get(message.DIRECT_CLS_HEADER)
        if direct_h_cls is not None:
            if direct_h_cls is not h_cls:
                return False
        return True

    return _matcher


def match_channel(desired_channel):
    def _matcher(channel):
        return channel == desired_channel
    return _matcher


def match_or(matcher, *more_matchers):
    matchers = [matcher]
    matchers.extend(more_matchers)

    def _matcher(m, h_cls, only_to_me=True):
        for m_func in matchers:
            if m_func(m, h_cls, only_to_me=only_to_me):
                return True
        return False

    return _matcher


def match_none(*args, **kwargs):
    return False


def match_any(*args, **kwargs):
    return True


def match_jira(*sub_components):
    return _make_matcher('jira', sub_components)


def match_sensu(*sub_components):
    return _make_matcher('sensu', sub_components)


def match_telnet(*sub_components):
    return _make_matcher('telnet', sub_components)


def match_slack(*sub_components):
    return _make_matcher('slack', sub_components)


def match_gerrit(*sub_components):
    return _make_matcher('gerrit', sub_components)


def match_github(*sub_components):
    return _make_matcher('github', sub_components)
