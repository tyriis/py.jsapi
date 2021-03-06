# Copyright © 2015 STRG.AT GmbH, Vienna, Austria
#
# This file is part of the The SCORE Framework.
#
# The SCORE Framework and all its parts are free software: you can redistribute
# them and/or modify them under the terms of the GNU Lesser General Public
# License version 3 as published by the Free Software Foundation which is in the
# file named COPYING.LESSER.txt.
#
# The SCORE Framework and all its parts are distributed without any WARRANTY;
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE. For more details see the GNU Lesser General Public
# License.
#
# If you have not received a copy of the GNU Lesser General Public License see
# http://www.gnu.org/licenses/.
#
# The License-Agreement realised between you as Licensee and STRG.AT GmbH as
# Licenser including the issue of its valid conclusion and its pre- and
# post-contractual effects is governed by the laws of Austria. Any disputes
# concerning this License-Agreement including the issue of its valid conclusion
# and its pre- and post-contractual effects are exclusively decided by the
# competent court, in whose district STRG.AT GmbH has its registered seat, at
# the discretion of STRG.AT GmbH also the competent court, in whose district the
# Licensee has his registered seat, an establishment or assets.

import inspect
import logging
import os
import textwrap
import json
from ._endpoint import UrlEndpoint

from score.init import (
    ConfigurationError, ConfiguredModule, parse_dotted_path,
    parse_list, parse_bool)


log = logging.getLogger(__name__)


defaults = {
    'endpoints': [],
    'expose': False,
    'js.require': 'lib/score/jsapi',
    'virtjs.path': 'jsapi.js',
}


def init(confdict, ctx, http, js=None):
    """
    Initializes this module acoording to :ref:`our module initialization
    guidelines <module_initialization>` with the following configuration keys:

    :confkey:`endpoints` :faint:`[default=list()]`
        A :func:`list <score.init.parse_list>` of :func:`dotted paths
        <score.init.parse_dotted_path>` pointing to any amount of
        :class:`Endpoints <.Endpoint>`. The registered functions of these
        Endpoints will be available in javascript.

    :confkey:`expose` :faint:`[default=False]`
        Whether security critical data may be exposed through the API. This
        value should be left at its default value in production, but may be
        switched to `True` during development to receive Exceptions and
        stacktraces in the browser console.

    :confkey:`js.require` :faint:`[default=lib/score/jsapi]`
        The name of the require.js module to create the virtual javascript with.
        When left at its default value, the resulting javascript can be included
        like the following:

        .. code-block:: javascript

            require(['lib/score/jsapi'], function(Api) {
                var api = new Api();
                // ... use api here ...
            });

    :confkey:`virtjs.path` :faint:`[default=jsapi.js]`
        Path of the :term:`virtual javascript <virtual asset>` file.
    """
    conf = dict(defaults.items())
    conf.update(confdict)
    endpoints = list(map(parse_dotted_path, parse_list(conf['endpoints'])))
    expose = parse_bool(conf['expose'])
    for endpoint in endpoints:
        for funcname in endpoint.ops:
            if funcname in js_keywords:
                raise ConfigurationError(
                    __package__,
                    'Exposed function `%s\'s name is '
                    'a reserved keyword in javascript' %
                    funcname)
            func = endpoint.ops[funcname]
            for name in inspect.signature(func).parameters:
                if name in js_keywords:
                    raise ConfigurationError(
                        __package__,
                        'Exposed function `%s\' has parameter `%s\', which is '
                        'a reserved keyword in javascript' %
                        (funcname, name))
        if not isinstance(endpoint, UrlEndpoint):
            continue
        name = endpoint.name
        api = _make_api(endpoint)
        http.newroute('score.jsapi:' + name, endpoint.url)(api)

    jsapi = ConfiguredJsapiModule(ctx, endpoints, expose,
                                  conf['js.require'])
    for endpoint in endpoints:
        endpoint.conf = jsapi

    if js:
        @js.virtjs(conf['virtjs.path'])
        def api(ctx):
            return jsapi.generate_js()

    return jsapi


js_keywords = (
    'abstract', 'arguments', 'boolean', 'break', 'byte', 'case', 'catch',
    'char', 'class*', 'const', 'continue', 'debugger', 'default', 'delete',
    'do', 'double', 'else', 'enum*', 'eval', 'export*', 'extends*', 'false',
    'final', 'finally', 'float', 'for', 'function', 'goto', 'if', 'implements',
    'import*', 'in', 'instanceof', 'int', 'interface', 'let', 'long', 'native',
    'new', 'null', 'package', 'private', 'protected', 'public', 'return',
    'short', 'static', 'super*', 'switch', 'synchronized', 'this', 'throw',
    'throws', 'transient', 'true', 'try', 'typeof', 'var', 'void', 'volatile',
    'while', 'with', 'yield',)


def _make_api(endpoint):
    def api(ctx):
        if endpoint.method == "POST":
            assert ctx.http.request.content_type == 'application/json'
            requests = json.loads(str(ctx.http.request.body,
                                      ctx.http.request.charset))
        else:
            requests = map(json.loads,
                           ctx.http.request.GET.getall('requests[]'))
        results = endpoint.handle(requests, {'http': ctx.http})
        ctx.http.response.content_type = 'application/json; charset=UTF-8'
        ctx.http.response.json = results
        return ctx.http.response
    return api


def _gen_apijs(endpoints, require_name):
    """
    Generates the :term:`virtual javascript <virtual asset>`.
    """
    op_defs = []
    op_funcs = []
    ep_defs = []
    for endpoint in endpoints:
        args = ''
        if endpoint._js_args:
            args = ', ' + ', '.join(endpoint._js_args)
        ep_defs.append("new Endpoint.{type}('{name}'{args});".format(
            name=endpoint.name, type=endpoint.type, args=args))
        for funcname in sorted(endpoint.ops):
            func = endpoint.ops[funcname]
            minargs = 0
            maxargs = 0
            argnames = []
            for name, param in inspect.signature(func).parameters.items():
                if name == 'ctx':
                    continue
                argnames.append(name)
                maxargs += 1
                if param.default == inspect.Parameter.empty:
                    minargs += 1
            op_def = """
                {name}: {0}
                    name: "{name}",
                    endpointId: "{endpoint}",
                    minargs: {minargs},
                    maxargs: {maxargs},
                    argnames: [{argnames}],
                {1}
            """.format(
                '{', '}', name=funcname, endpoint=endpoint.name,
                minargs=minargs, maxargs=maxargs,
                argnames=', '.join(map(lambda x: '"%s"' % x, argnames)))
            op_defs.append(
                textwrap.indent(textwrap.dedent(op_def).strip(), ' ' * 16))
            doc = ''
            if func.__doc__:
                doc = textwrap.dedent(func.__doc__).strip()
                doc = doc.replace('*/', '* /')
                doc = doc.replace('\n', '\n *')
                doc = '/**\n * %s\n */\n' % doc
            args = ''
            if argnames:
                args = ', ' + ', '.join(argnames)
            op_func = """
                {name}: function(self{args}) {0}
                    var args = [];
                    for (var i = 1; i < arguments.length; i++) {0}
                        args.push(arguments[i])
                    {1}
                    var promise = self._call('{name}', args);
                    self._flush();
                    return promise;
                {1}
            """.format('{', '}', name=funcname, args=args)
            op_funcs.append(
                textwrap.indent(doc, ' ' * 8) +
                textwrap.indent(textwrap.dedent(op_func).strip(), ' ' * 8))
    op_defs = ',\n\n'.join(op_defs).strip()
    op_funcs = ',\n\n'.join(op_funcs).strip()
    ep_defs = '\n\n'.join(ep_defs)
    return api_tpl % (require_name, op_defs, op_funcs, ep_defs)


class ConfiguredJsapiModule(ConfiguredModule):
    """
    This module's :class:`configuration class
    <score.init.ConfiguredModule>`.
    """

    def __init__(self, ctx_conf, endpoints, expose, require_name):
        super().__init__(__package__)
        self.ctx_conf = ctx_conf
        self.endpoints = endpoints
        self.expose = expose
        self.require_name = require_name

    def generate_js(self):
        if not hasattr(self, '__generated_js'):
            self.__generated_js = _gen_apijs(self.endpoints, self.require_name)
        return self.__generated_js


here = os.path.abspath(os.path.dirname(__file__))
file = os.path.join(here, 'api.js.tpl')
api_tpl = open(file).read()
