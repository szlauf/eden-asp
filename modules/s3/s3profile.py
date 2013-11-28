# -*- coding: utf-8 -*-

""" S3 Profile

    @copyright: 2009-2013 (c) Sahana Software Foundation
    @license: MIT

    Permission is hereby granted, free of charge, to any person
    obtaining a copy of this software and associated documentation
    files (the "Software"), to deal in the Software without
    restriction, including without limitation the rights to use,
    copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the
    Software is furnished to do so, subject to the following
    conditions:

    The above copyright notice and this permission notice shall be
    included in all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
    EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
    OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
    NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
    HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
    WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
    FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
    OTHER DEALINGS IN THE SOFTWARE.
"""

from gluon import current
from gluon.html import *
from gluon.http import redirect
from gluon.storage import Storage

from s3crud import S3CRUD
from s3data import S3DataList
from s3resource import S3FieldSelector

# =============================================================================
class S3Profile(S3CRUD):
    """
        Interactive Method Handler for Profile Pages

        Configure widgets using s3db.configure(tablename, profile_widgets=[])

        @ToDo: Make more configurable:
           * Currently assumes a max of 2 widgets per row
           * Currently uses internal widgets rather than S3Method widgets

        @todo:
            - unify datalist and datatable methods with the superclass
              methods (requires re-design of the superclass methods)
            - allow as default handler for interactive single-record-no-method
              GET requests (include read/update from superclass)
    """

    # -------------------------------------------------------------------------
    def apply_method(self, r, **attr):
        """
            API entry point

            @param r: the S3Request instance
            @param attr: controller attributes for the request
        """

        if r.http in ("GET", "POST", "DELETE"):
            if r.record:
                output = self.profile(r, **attr)
            else:
                # Redirect to the List View
                redirect(r.url(method=""))
        else:
            r.error(405, r.ERROR.BAD_METHOD)
        return output

    # -------------------------------------------------------------------------
    def profile(self, r, **attr):
        """
            Generate a Profile page

            @param r: the S3Request instance
            @param attr: controller attributes for the request
        """

        response = current.response

        tablename = self.tablename
        get_config = current.s3db.get_config

        # Page Title
        title = get_config(tablename, "profile_title")
        if not title:
            try:
                title = r.record.name
            except:
                title = current.T("Profile Page")
        elif callable(title):
            title = title(r)

        # Page Header
        header = get_config(tablename, "profile_header")
        if not header:
            header = H2(title, _class="profile_header")
        elif callable(header):
            header = header(r)

        output = dict(title=title, header=header)

        # Get the page widgets
        widgets = get_config(tablename, "profile_widgets")
        if widgets:

            # Index the widgets by their position in the config
            for index, widget in enumerate(widgets):
                widget["index"] = index

            if r.representation == "dl":
                # Ajax-update of one datalist
                get_vars = r.get_vars
                index = r.get_vars.get("update", None)
                if index:
                    try:
                        index = int(index)
                    except ValueError:
                        datalist = ""
                    else:
                        # @ToDo: Check permissions to the Resource & do
                        # something different if no permission
                        datalist = self._datalist(r, widgets[index], **attr)
                output["item"] = datalist

            elif r.representation == "aadata":
                # Ajax-update of one datalist
                get_vars = r.get_vars
                index = r.get_vars.get("update", None)
                if index:
                    try:
                        index = int(index)
                    except ValueError:
                        datalist = ""
                    else:
                        # @ToDo: Check permissions to the Resource & do
                        # something different if no permission
                        datatable = self._datatable(r, widgets[index], **attr)
                return datatable

            else:
                # Default page-load
                rows = []
                append = rows.append
                row = None
                for widget in widgets:

                    # Render the widget
                    w_type = widget["type"]
                    if w_type == "comments":
                        w = self._comments(r, widget, **attr)
                    elif w_type == "datalist":
                        w = self._datalist(r, widget, **attr)
                    elif w_type == "datatable":
                        w = self._datatable(r, widget, **attr)
                    elif w_type == "form":
                        w = self._form(r, widget, **attr)
                    elif w_type == "map":
                        w = self._map(r, widget, **attr)
                    else:
                        if response.s3.debug:
                            raise SyntaxError("Unsupported widget type %s" %
                                              w_type)
                        else:
                            # ignore
                            continue

                    colspan = widget.get("colspan", 1)
                    if colspan > 1 and row:
                        # Close previous row
                        append(row)
                        row = None
                        
                    if row is None:
                        # Start new row
                        row = DIV(_class="row profile")
                        
                    # Append widget to row
                    row.append(w)
                    
                    if colspan > 1 or len(row) > 1:
                        # Close this row
                        append(row)
                        row = None

                output["rows"] = rows
                response.view = self._view(r, "profile.html")

        else:
            output["rows"] = []

        return output

    # -------------------------------------------------------------------------
    @staticmethod
    def _resolve_context(context, id):
        """
            Resolve a context filter

            @param context: the context (as a string)
            @param id: the record_id
        """

        if context == "location":
            # Show records linked to this Location & all it's Child Locations
            s = "(location)$path"
            # This version doesn't serialize_url
            #m = ("%(id)s/*,*/%(id)s/*" % dict(id=id)).split(",")
            #filter = (S3FieldSelector(s).like(m)) | (S3FieldSelector(s) == id)
            m = ("%(id)s,%(id)s/*,*/%(id)s/*,*/%(id)s" % dict(id=id)).split(",")
            m = [f.replace("*", "%") for f in m]
            filter = S3FieldSelector(s).like(m)
        # @ToDo:
        #elif context == "organisation":
        #    # Show records linked to this Organisation and all it's Branches
        #    s = "(%s)" % context
        #    filter = S3FieldSelector(s) == id
        else:
            # Normal: show just records linked directly to this master resource
            s = "(%s)" % context
            filter = S3FieldSelector(s) == id

        return filter

    # -------------------------------------------------------------------------
    def _comments(self, r, widget, **attr):
        """
            Generate a Comments widget

            @param r: the S3Request instance
            @param widget: the widget as a tuple: (label, type, icon)
            @param attr: controller attributes for the request

            @ToDo: Configurable to use either Disqus or internal Comments
        """

        label = widget.get("label", "")
        if label:
            label = current.T(label)
        icon = widget.get("icon", "")
        if icon:
            icon = TAG[""](I(_class=icon), " ")

        # Render the widget
        output = DIV(H4(icon,
                        label,
                        _class="profile-sub-header"),
                     DIV(_class="thumbnail"),
                     _class="span12")

        return output

    # -------------------------------------------------------------------------
    def _datalist(self, r, widget, **attr):
        """
            Generate a data list

            @param r: the S3Request instance
            @param widget: the widget definition as dict
            @param attr: controller attributes for the request
        """

        T = current.T
        s3db = current.s3db
        id = r.id
        context = widget.get("context", None)
        if context:
            context = self._resolve_context(context, id)
        s3db.context = context

        tablename = widget.get("tablename", None)
        resource = s3db.resource(tablename, context=True)

        # Config Options:
        # 1st choice: Widget
        # 2nd choice: get_config
        # 3rd choice: Default
        config = resource.get_config
        list_fields = widget.get("list_fields", 
                                 config("list_fields", None))
        list_layout = widget.get("list_layout", 
                                 config("list_layout", None))
        orderby = widget.get("orderby",
                             config("list_orderby",
                                    ~resource.table.created_on))

        filter = widget.get("filter", None)
        if filter:
            resource.add_filter(filter)

        # Use the widget-index to create a unique ID
        listid = "profile-list-%s-%s" % (tablename, widget["index"])

        # Page size
        pagesize = widget.get("pagesize", 4)
        representation = r.representation
        if representation == "dl":
            # Ajax-update
            get_vars = r.get_vars
            record_id = get_vars.get("record", None)
            if record_id is not None:
                # Ajax-update of a single record
                resource.add_filter(S3FieldSelector("id") == record_id)
                start, limit = 0, 1
            else:
                # Ajax-update of full page
                start = get_vars.get("start", None)
                limit = get_vars.get("limit", None)
                if limit is not None:
                    try:
                        start = int(start)
                        limit = int(limit)
                    except ValueError:
                        start, limit = 0, pagesize
                else:
                    start = None
        else:
            # Page-load
            start, limit = 0, pagesize

        # Ajax-delete items?
        if representation == "dl" and r.http in ("DELETE", "POST"):
            if "delete" in r.get_vars:
                return self._dl_ajax_delete(r, resource)
            else:
                r.error(405, r.ERROR.BAD_METHOD)

        # dataList
        datalist, numrows, ids = resource.datalist(fields=list_fields,
                                                   start=start,
                                                   limit=limit,
                                                   listid=listid,
                                                   orderby=orderby,
                                                   layout=list_layout)
        # Render the list
        ajaxurl = r.url(vars={"update": widget["index"]},
                        representation="dl")
        data = datalist.html(ajaxurl=ajaxurl,
                             pagesize=pagesize,
                             empty = P(I(_class="icon-folder-open-alt"),
                                       BR(),
                                       S3CRUD.crud_string(tablename,
                                                          "msg_no_match"),
                                       _class="empty_card-holder"
                                      ),
                             )

        if representation == "dl":
            # This is an Ajax-request, so we don't need the wrapper
            current.response.view = "plain.html"
            return data

        # Interactive only below here
        label = widget.get("label", "")
        if label:
            label = T(label)
        icon = widget.get("icon", "")
        if icon:
            icon = TAG[""](I(_class=icon), " ")

        s3 = current.response.s3

        if pagesize and numrows > pagesize:
            # Button to display the rest of the records in a Modal
            more = numrows - pagesize
            vars = {}
            if context:
                filters = context.serialize_url(resource)
                for f in filters:
                    vars[f] = filters[f]
            if filter:
                filters = filter.serialize_url(resource)
                for f in filters:
                    vars[f] = filters[f]
            c, f = tablename.split("_", 1)
            url = URL(c=c, f=f, args=["datalist.popup"],
                      vars=vars)
            more = DIV(A(BUTTON("%s (%s)" % (T("see more"), more),
                                _class="btn btn-mini",
                                _type="button",
                                ),
                         _class="s3_modal",
                         _href=url,
                         _title=label,
                         ),
                       _class="more_profile")
        else:
            more = ""

        # Link for create-popup
        create_popup = self._create_popup(r,
                                          widget,
                                          listid,
                                          resource,
                                          context,
                                          numrows)

        # Render the widget
        output = DIV(create_popup,
                     H4(icon,
                        label,
                        _class="profile-sub-header"),
                     DIV(data,
                         more,
                         _class="card-holder"),
                     _class="span6")

        return output

    # -------------------------------------------------------------------------
    def _datatable(self, r, widget, **attr):
        """
            Generate a data table.

            @param r: the S3Request instance
            @param widget: the widget definition as dict
            @param attr: controller attributes for the request

            @todo: fix export formats
        """

        T = current.T

        # Parse context
        s3db = current.s3db
        record_id = r.id
        context = widget.get("context", None)
        if context:
            context = self._resolve_context(context, record_id)
        s3db.context = context

        # Define target resource
        tablename = widget.get("tablename", None)
        resource = s3db.resource(tablename, context=True)
        table = resource.table
        get_config = resource.get_config

        # List fields
        list_fields = widget.get("list_fields",
                                 get_config("list_fields", None))
        if not list_fields:
            list_fields = [f for f in table.fields if table[f].readable]
            if "id" not in list_fields:
                list_fields.append("id")

        # Widget filter option
        widget_filter = widget.get("filter", None)
        if widget_filter:
            resource.add_filter(widget_filter)

        # Use the widget-index to create a unique ID
        listid = "profile-list-%s-%s" % (tablename, widget["index"])

        # Default ORDERBY
        # - first field actually in this table
        def default_orderby():
            for f in list_fields:
                if f == "id":
                    continue
                rfield = resource.resolve_selector(f)
                if rfield.field:
                    return rfield.field
            return None

        # Pagination
        representation = r.representation
        get_vars = self.request.get_vars
        if representation == "aadata":
            start = get_vars.get("iDisplayStart", None)
            limit = get_vars.get("iDisplayLength", 0)
        else:
            start = get_vars.get("start", None)
            limit = get_vars.get("limit", 0)
        if limit:
            if limit.lower() == "none":
                limit = None
            else:
                try:
                    start = int(start)
                    limit = int(limit)
                except ValueError:
                    start = None
                    limit = 0 # use default
        else:
            # Use defaults
            start = None

        dtargs = attr.get("dtargs", {})
        
        if r.interactive:
            s3 = current.response.s3
            
            # How many records per page?
            if s3.dataTable_iDisplayLength:
                display_length = s3.dataTable_iDisplayLength
            else:
                display_length = widget.get("pagesize", 10)
            if not display_length:
                display_length = 10

            # ORDERBY fallbacks: widget->resource->default
            orderby = widget.get("orderby")
            if not orderby:
                orderby = get_config("orderby")
            if not orderby:
                orderby = default_orderby()

            # Server-side pagination?
            if not s3.no_sspag:
                dt_pagination = "true"
                if not limit:
                    limit = 2 * display_length
            else:
                dt_pagination = "false"

            # Get the data table
            dt, totalrows, ids = resource.datatable(fields=list_fields,
                                                    start=start,
                                                    limit=limit,
                                                    orderby=orderby)
            displayrows = totalrows

            if dt.empty:
                empty_str = self.crud_string(tablename,
                                             "msg_list_empty")
            else:
                empty_str = self.crud_string(tablename,
                                             "msg_no_match")
            empty = DIV(empty_str, _class="empty")

            dtargs["dt_pagination"] = dt_pagination
            dtargs["dt_displayLength"] = display_length
            # @todo: fix base URL (make configurable?) to fix export options
            s3.no_formats = True
            dtargs["dt_base_url"] = r.url(method="", vars={})
            dtargs["dt_ajax_url"] = r.url(vars={"update": widget["index"]},
                                            representation="aadata")
            actions = widget.get("actions")
            if callable(actions):
                actions = actions(r, listid)
            if actions:
                dtargs["dt_row_actions"] = actions
            datatable = dt.html(totalrows,
                                displayrows,
                                id=listid,
                                **dtargs)

            if dt.data:
                empty.update(_style="display:none;")
            else:
                datatable.update(_style="display:none;")
            contents = DIV(datatable, empty, _class="dt-contents")

            # Link for create-popup
            create_popup = self._create_popup(r,
                                              widget,
                                              listid,
                                              resource,
                                              context,
                                              totalrows)

            # Card holder label and icon
            label = widget.get("label", "")
            if label:
                label = T(label)
            icon = widget.get("icon", "")
            if icon:
                icon = TAG[""](I(_class=icon), " ")

            # Render the widget
            output = DIV(create_popup,
                         H4(icon, label,
                            _class="profile-sub-header"),
                         DIV(contents,
                             _class="card-holder"),
                         _class="span6")

            return output

        elif representation == "aadata":

            # Parse datatable filter/sort query
            searchq, orderby, left = resource.datatable_filter(list_fields,
                                                               get_vars)
                                                               
            # ORDERBY fallbacks - datatable->widget->resource->default
            if not orderby:
                orderby = widget.get("orderby")
            if not orderby:
                orderby = get_config("orderby")
            if not orderby:
                orderby = default_orderby()

            # DataTable filtering
            if searchq is not None:
                totalrows = resource.count()
                resource.add_filter(searchq)
            else:
                totalrows = None

            # Get the data table
            if totalrows != 0:
                dt, displayrows, ids = resource.datatable(fields=list_fields,
                                                          start=start,
                                                          limit=limit,
                                                          left=left,
                                                          orderby=orderby,
                                                          getids=False)
            else:
                dt, displayrows = None, 0
                
            if totalrows is None:
                totalrows = displayrows

            # Echo
            sEcho = int(get_vars.sEcho or 0)

            # Representation
            if dt is not None:
                data = dt.json(totalrows,
                               displayrows,
                               listid,
                               sEcho,
                               **dtargs)
            else:
                data = '{"iTotalRecords":%s,' \
                       '"iTotalDisplayRecords":0,' \
                       '"dataTable_id":"%s",' \
                       '"sEcho":%s,' \
                       '"aaData":[]}' % (totalrows, listid, sEcho)

            return data
            
        else:
            # Really raise an exception here?
            r.error(501, r.ERROR.BAD_FORMAT)

    # -------------------------------------------------------------------------
    def _form(self, r, widget, **attr):
        """
            Generate a Form widget

            @param r: the S3Request instance
            @param widget: the widget as a tuple: (label, type, icon)
            @param attr: controller attributes for the request
        """

        s3db = current.s3db

        label = widget.get("label", "")
        if label:
            label = current.T(label)
        icon = widget.get("icon", "")
        if icon:
            icon = TAG[""](I(_class=icon), " ")

        tablename = widget.get("tablename")

        context = widget.get("context", None)
        if context:
            context = self._resolve_context(context, r.id)
        s3db.context = context
        resource = s3db.resource(tablename, context=True)
        record = resource.select(["id"], limit=1, as_rows=True).first()
        if record:
            record_id = record.id
        else:
            record_id = None

        if record_id:
            readonly = not current.auth.s3_has_permission("update", tablename, record_id)
        else:
            readonly = not current.auth.s3_has_permission("create", tablename)

        sqlform = widget.get("sqlform", None)
        if not sqlform:
            sqlform = current.deployment_settings.get_ui_crud_form(tablename)
            if not sqlform:
                from s3forms import S3SQLDefaultForm
                sqlform = S3SQLDefaultForm()

        form = sqlform(request = r,
                       resource = resource,
                       record_id = record_id,
                       readonly = readonly,
                       format = "html",
                       )

        # Render the widget
        output = DIV(H4(icon,
                        label,
                        _class="profile-sub-header"),
                     DIV(form,
                         _class="form-container thumbnail"),
                     _class="span12")

        return output

    # -------------------------------------------------------------------------
    def _map(self, r, widget, **attr):
        """
            Generate a Map widget

            @param r: the S3Request instance
            @param widget: the widget as a tuple: (label, type, icon)
            @param attr: controller attributes for the request
        """

        from s3gis import Marker

        T = current.T
        db = current.db
        s3db = current.s3db

        label = widget.get("label", "")
        if label:
            label = current.T(label)
        icon = widget.get("icon", "")
        if icon:
            icon = TAG[""](I(_class=icon), " ")
        context = widget.get("context", None)
        if context:
            context = self._resolve_context(context, r.id)
            cserialize_url = context.serialize_url

        height = widget.get("height", 383)
        width = widget.get("width", 568) # span6 * 99.7%
        bbox = widget.get("bbox", {})

        # Default to showing all the resources in datalist widgets as separate layers
        ftable = s3db.gis_layer_feature
        mtable = s3db.gis_marker
        feature_resources = []
        fappend = feature_resources.append
        widgets = s3db.get_config(r.tablename, "profile_widgets")
        s3dbresource = s3db.resource
        for widget in widgets:
            if widget["type"] != "datalist":
                continue
            show_on_map = widget.get("show_on_map", True)
            if not show_on_map:
                continue
            # @ToDo: Check permission to access layer (both controller/function & also within Map Config)
            tablename = widget["tablename"]
            listid = "profile-list-%s-%s" % (tablename, widget["index"])
            layer = dict(name = T(widget["label"]),
                         id = listid,
                         active = True,
                         )
            filter = widget.get("filter", None)
            marker = widget.get("marker", None)
            if marker:
                marker = db(mtable.name == marker).select(mtable.image,
                                                          mtable.height,
                                                          mtable.width,
                                                          limitby=(0, 1)).first()
            layer_id = None
            layer_name = widget.get("layer", None)
            if layer_name:
                row = db(ftable.name == layer_name).select(ftable.layer_id,
                                                           limitby=(0, 1)).first()
                if row:
                    layer_id = row.layer_id
            if layer_id:
                layer["layer_id"] = layer_id
                resource = s3dbresource(tablename)
                filter_url = ""
                first = True
                if context:
                    filters = cserialize_url(resource)
                    for f in filters:
                        sep = "" if first else "&"
                        filter_url = "%s%s%s=%s" % (filter_url, sep, f, filters[f])
                        first = False
                if filter:
                    filters = filter.serialize_url(resource)
                    for f in filters:
                        sep = "" if first else "&"
                        filter_url = "%s%s%s=%s" % (filter_url, sep, f, filters[f])
                        first = False
                if filter_url:
                    layer["filter"] = filter_url
            else:
                layer["tablename"] = tablename
                map_url = widget.get("map_url", None)
                if not map_url:
                    # Build one
                    c, f = tablename.split("_", 1)
                    map_url = URL(c=c, f=f, extension="geojson")
                    resource = s3dbresource(tablename)
                    first = True
                    if context:
                        filters = cserialize_url(resource)
                        for f in filters:
                            sep = "?" if first else "&"
                            map_url = "%s%s%s=%s" % (map_url, sep, f, filters[f])
                            first = False
                    if filter:
                        filters = filter.serialize_url(resource)
                        for f in filters:
                            sep = "?" if first else "&"
                            map_url = "%s%s%s=%s" % (map_url, sep, f, filters[f])
                            first = False
                layer["url"] = map_url

            if marker:
                layer["marker"] = marker

            fappend(layer)

        map = current.gis.show_map(height=height,
                                   width=width,
                                   bbox=bbox,
                                   collapsed=True,
                                   feature_resources=feature_resources,
                                   )

        # Button to go full-screen
        fullscreen = A(I(_class="icon icon-fullscreen"),
                       _href=URL(c="gis", f="map_viewing_client"),
                       _class="gis_fullscreen_map-btn",
                       # If we need to support multiple maps on a page
                       #_map="default",
                       _title=T("View full screen"),
                       )
        s3 = current.response.s3
        if s3.debug:
            script = "/%s/static/scripts/S3/s3.gis.fullscreen.js" % current.request.application
        else:
            script = "/%s/static/scripts/S3/s3.gis.fullscreen.min.js" % current.request.application
        s3.scripts.append(script)

        # Render the widget
        output = DIV(fullscreen,
                     H4(icon,
                        label,
                        _class="profile-sub-header"),
                     DIV(map,
                         _class="card-holder"),
                     _class="span6")

        return output

    # -------------------------------------------------------------------------
    def _create_popup(self, r, widget, listid, resource, context, numrows):
        """
            Render an action link for a create-popup (used in data lists
            and data tables).

            @param r: the S3Request instance
            @param widget: the widget definition as dict
            @param listid: the list ID
            @param resource: the target resource
            @param context: the context filter
            @param numrows: the total number of rows in the list/table
        """
        
        create = ""
        insert = widget.get("insert", True)
        
        table = resource.table
        if insert and current.auth.s3_has_permission("create", table):
            
            tablename = resource.tablename
            
            #if tablename = "org_organisation":
                # @ToDo: Special check for creating resources on Organisation profile

            # URL-serialize the widget filter
            widget_filter = widget.get(filter)
            if widget_filter:
                vars = widget_filter.serialize_url(widget_filter)
            else:
                vars = Storage()

            # URL-serialize the context filter
            if context:
                filters = context.serialize_url(resource)
                for f in filters:
                    vars[f] = filters[f]

            # URL-serialize the widget default
            default = widget.get("default")
            if default:
                k, v = default.split("=", 1)
                vars[k] = v

            # URL-serialize the list ID (refresh-target of the popup)
            vars.refresh = listid

            # CRUD string
            title_create = widget.get("title_create", None)
            if title_create:
                title_create = current.T(title_create)
            else:
                title_create = S3CRUD.crud_string(tablename, "title_create")

            # Popup URL
            # Default to primary REST controller for the resource being added
            c, f = tablename.split("_", 1)
            c = widget.get("create_controller", c)
            f = widget.get("create_function", f)
            component = widget.get("create_component", None)
            if component:
                args = [r.id, component, "create.popup"]
            else:
                args = ["create.popup"]
            add_url = URL(c=c, f=f, args=args, vars=vars)

            if callable(insert):
                # Custom widget
                create = insert(r, listid, title_create, add_url)
                
            elif current.response.s3.crud.formstyle == "bootstrap":
                # Bootstrap-style action icon
                create = A(I(_class="icon icon-plus-sign small-add"),
                           _href=add_url,
                           _class="s3_modal",
                           _title=title_create,
                           )
            else:
                # Standard action button
                create = A(title_create,
                           _href=add_url,
                           _class="action-btn profile-add-btn s3_modal",
                           )

            if widget.get("type") == "datalist":
                
                # If this is a multiple=False widget and we already
                # have a record, we hide the create-button
                multiple = widget.get("multiple", True)
                if not multiple and hasattr(create, "update"):
                    if numrows:
                        create.update(_style="display:none;")
                    else:
                        create.update(_style="display:block;")
                    # Script to hide/unhide the create-button on Ajax
                    # list updates
                    createid = create["_id"]
                    if not createid:
                        createid = "%s-add-button" % listid
                        create.update(_id=createid)
                    script = \
'''$('#%(listid)s').on('listUpdate',function(){
$('#%(createid)s').css({display:$(this).datalist('getTotalItems')?'none':'block'})
})''' % dict(listid=listid, createid=createid)
                    s3.jquery_ready.append(script)

        return create

# END =========================================================================
