"""
    Supply Model

    Copyright: 2009-2024 (c) Sahana Software Foundation

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

__all__ = ("SupplyCatalogModel",
           "SupplyItemModel",
           "SupplyItemEntityModel",
           "SupplyItemAlternativesModel",
           "SupplyItemBrandModel",
           "SupplyPersonModel",
           "SupplyDistributionModel",
           "supply_item_rheader",
           "supply_item_controller",
           "supply_item_entity_controller",
           "supply_catalog_rheader",
           "supply_distribution_rheader",
           "supply_item_entity_category",
           "supply_item_entity_country",
           "supply_item_entity_organisation",
           "supply_item_entity_contacts",
           "supply_item_entity_status",
           "supply_ItemRepresent",
           "supply_ItemCategoryRepresent",
           "supply_get_shipping_code",
           "supply_item_pack_quantities",
           )

import re

from collections import OrderedDict

from gluon import *
from gluon.storage import Storage

from ..core import *
from s3dal import Row
from core.ui.layouts import PopupLink

# @ToDo: Put the most common patterns at the top to optimise
UM_PATTERNS = (r"\sper\s?(.*)$",                         # CHOCOLATE, per 100g
               #r"\((.*)\)$",                            # OUTWARD REGISTER for shipping (50 sheets)
               r"([0-9]+\s?(gramm?e?s?|L|g|kg))$",       # Navarin de mouton 285 grammes
               r",\s(kit|pair|btl|bottle|tab|vial)\.?$", # STAMP, IFRC, Englishlue, btl.
               r"\s(bottle)\.?$",                        # MINERAL WATER, 1.5L bottle
               r",\s((bag|box|kit) of .*)\.?$",          # (bag, diplomatic) LEAD SEAL, bag of 100
               )

# =============================================================================
class SupplyCatalogModel(DataModel):
    """ Catalogs and categories of supply items """

    names = ("supply_catalog",
             "supply_catalog_id",
             "supply_item_category",
             "supply_item_category_id",
             )

    def model(self):

        T = current.T
        db = current.db
        s3 = current.response.s3
        settings = current.deployment_settings

        # Shortcuts
        add_components = self.add_components
        configure = self.configure
        crud_strings = s3.crud_strings
        define_table = self.define_table

        translate = settings.get_L10n_translate_supply_item()
        if translate:
            translate_represent = T
        else:
            translate_represent = None

        # TODO not useful with org-specific catalogs:
        catalog_multi = settings.get_supply_catalog_multi()

        # =====================================================================
        # Catalog (of Items)
        #
        tablename = "supply_catalog"
        define_table(tablename,
                     self.org_organisation_id(comment=None),
                     Field("name", length=128,
                           label = T("Name"),
                           # TODO No point translating catalog names?
                           represent = translate_represent,
                           requires = [IS_NOT_EMPTY(),
                                       IS_LENGTH(128),
                                       # TODO Modify uniqueness requirement
                                       #      - should be unique within organisation
                                       #      - move thus into onvalidation?
                                       # IS_NOT_ONE_OF(db, "%s.name" % tablename),
                                       ],
                           ),
                     Field("active", "boolean",
                           label = T("Active"),
                           default = True,
                           represent = BooleanRepresent(icons=True, colors=True),
                           ),
                     CommentsField(),
                     )

        # Components
        add_components(tablename,
                       # Categories
                       supply_item_category = "catalog_id",
                       # Catalog Items
                       supply_catalog_item = "catalog_id",
                       )

        # Filter widgets
        filter_widgets = [TextFilter(["name", "comments"],
                                     label = T("Search"),
                                     ),
                          ]

        # Table configuration
        configure(tablename,
                  deduplicate = S3Duplicate(primary=("name",),
                                            secondary=("organisation_id",),
                                            ),
                  deletable = False,
                  filter_widgets = filter_widgets,
                  onvalidation = self.catalog_onvalidation,
                  realm_components = ("item_category", "catalog_item"),
                  update_realm = True,
                  )

        # CRUD strings
        ADD_CATALOG = T("Create Catalog")
        crud_strings[tablename] = Storage(
            label_create = ADD_CATALOG,
            title_display = T("Catalog Details"),
            title_list = T("Catalogs"),
            title_update = T("Edit Catalog"),
            label_list_button = T("List Catalogs"),
            label_delete_button = T("Delete Catalog"),
            msg_record_created = T("Catalog added"),
            msg_record_modified = T("Catalog updated"),
            msg_record_deleted = T("Catalog deleted"),
            msg_list_empty = T("No Catalogs currently registered"))

        # Foreign Key Template
        represent = S3Represent(lookup=tablename, translate=translate)
        catalog_id = FieldTemplate("catalog_id", "reference %s" % tablename,
                                   label = T("Catalog"),
                                   ondelete = "RESTRICT",
                                   represent = represent,
                                   requires = IS_EMPTY_OR(
                                                    IS_ONE_OF(db, "supply_catalog.id",
                                                              represent,
                                                              sort = True,
                                                              # Restrict to catalogs the user can update
                                                              updateable = True,
                                                              )),
                                   sortby = "name",
                                   readable = catalog_multi,
                                   writable = catalog_multi,
                                   )

        # =====================================================================
        # Item Category
        #
        category_hierarchy = settings.get_supply_item_category_hierarchy()

        asset = settings.has_module("asset")
        telephone = settings.get_asset_telephones()
        vehicle = settings.has_module("vehicle")

        item_category_represent = supply_ItemCategoryRepresent(translate=translate)
        item_category_represent_nocodes = \
            supply_ItemCategoryRepresent(translate=translate, use_code=False)

        if format in ("xlsx", "xls"):
            parent_represent = item_category_represent_nocodes
        else:
            parent_represent = item_category_represent

        item_category_requires = IS_EMPTY_OR(
                                    IS_ONE_OF(db, "supply_item_category.id",
                                              item_category_represent_nocodes,
                                              sort=True)
                                    )

        tablename = "supply_item_category"
        define_table(tablename,
                     catalog_id(),
                     Field("parent_item_category_id",
                           "reference supply_item_category",
                           label = T("Parent Category"),
                           ondelete = "RESTRICT",
                           represent = parent_represent,
                           readable = category_hierarchy,
                           writable = category_hierarchy,
                           ),
                     Field("code", length=16,
                           label = T("Code"),
                           requires = IS_LENGTH(16),
                           ),
                     Field("name", length=128,
                           label = T("Name"),
                           represent = translate_represent,
                           requires = IS_LENGTH(128),
                           ),
                     Field("can_be_asset", "boolean",
                           default = True,
                           label = T("Items in Category can be Assets"),
                           represent = s3_yes_no_represent,
                           readable = asset,
                           writable = asset,
                           ),
                     # TODO drop this field
                     Field("is_telephone", "boolean",
                           default = False,
                           label = T("Items in Category are Telephones"),
                           represent = s3_yes_no_represent,
                           readable = telephone,
                           writable = telephone,
                           ),
                     Field("is_vehicle", "boolean",
                           default = False,
                           label = T("Items in Category are Vehicles"),
                           represent = s3_yes_no_represent,
                           readable = vehicle,
                           writable = vehicle,
                           ),
                     CommentsField(),
                     on_define = lambda table: \
                        [table.parent_item_category_id.set_attributes(requires = item_category_requires),
                         ]
                     )

        # CRUD strings
        crud_strings[tablename] = Storage(
            label_create = T("Create Item Category"),
            title_display = T("Item Category Details"),
            title_list = T("Item Categories"),
            title_update = T("Edit Item Category"),
            label_list_button = T("List Item Categories"),
            label_delete_button = T("Delete Item Category"),
            msg_record_created = T("Item Category added"),
            msg_record_modified = T("Item Category updated"),
            msg_record_deleted = T("Item Category deleted"),
            msg_list_empty = T("No Item Categories currently registered"))

        # Field template
        item_category_id = FieldTemplate("item_category_id", "reference %s" % tablename,
                                         label = T("Category"),
                                         ondelete = "RESTRICT",
                                         represent = item_category_represent,
                                         requires = item_category_requires,
                                         sortby = "name",
                                         )

        # Components
        if category_hierarchy:
            # Child categories
            add_components(tablename,
                           supply_item_category = "parent_item_category_id",
                           )

        configure(tablename,
                  deduplicate = self.item_category_duplicate,
                  onvalidation = self.item_category_onvalidation,
                  )

        # ---------------------------------------------------------------------
        # Pass names back to global scope (s3.*)
        #
        return {"supply_catalog_id": catalog_id,
                "supply_item_category_id": item_category_id,
                "supply_item_category_represent": item_category_represent,
                }

    # -------------------------------------------------------------------------
    def defaults(self):
        """ Return safe defaults for names in case the model is disabled """

        dummy = FieldTemplate.dummy

        return {"supply_catalog_id": dummy("catalog_id"),
                "supply_item_category_id": dummy("item_category_id"),
                }

    # -------------------------------------------------------------------------
    @staticmethod
    def catalog_onvalidation(form):
        """
            Form validation of catalogs
                - name must be unique (within the organisation)

            Args:
                form: the FORM
        """

        db = current.db
        s3db = current.s3db

        table = s3db.supply_catalog

        # Get form record ID
        record_id = get_form_record_id(form)

        # Get form record data
        data = get_form_record_data(form, table, ["organisation_id", "name"])
        organisation_id = data.get("organisation_id")
        name = data.get("name")

        query = (table.name == name)
        if record_id:
            query &= (table.id != record_id)
        if organisation_id:
            query &= (table.organisation_id == organisation_id) | \
                     (table.organisation_id == None)
        query &= (table.deleted == False)
        if db(query).select(table.id, limitby=(0, 1)).first():
            form.errors.name = current.T("A catalog with that name already exists")

    # -------------------------------------------------------------------------
    @staticmethod
    def item_category_onvalidation(form):
        """
            Category form validation:
                - must have either a code or a name
                - code and name must be unique within the catalog

            Args:
                form: the FORM
        """

        T = current.T

        db = current.db
        s3db = current.s3db

        table = s3db.supply_item_category

        # Get form record ID
        record_id = get_form_record_id(form)

        # Get form record data
        data = get_form_record_data(form, table, ["catalog_id", "name", "code"])
        catalog_id = data.get("catalog_id")
        name = data.get("name")
        code = data.get("code")

        # Must have a code or a name
        form_errors = form.errors
        if not name and not code:
            error = T("An Item Category must have a Code OR a Name.")
            form_errors.code = form_errors.name = error

        elif catalog_id:
            query = (table.catalog_id == catalog_id)
            if record_id:
                query &= (table.id != record_id)
            for fn in ("name", "code"):
                value = data.get(fn)
                if not value:
                    continue
                q = query & (table[fn] == value) & (table.deleted == False)
                if db(q).select(table.id, limitby=(0, 1)).first():
                    form_errors[fn] = T("A category with this label already exists in this catalog")

    # -------------------------------------------------------------------------
    @staticmethod
    def item_category_duplicate(item):
        """
            Callback function used to look for duplicates during
            the import process

            Args:
                item: the ImportItem to check
        """

        data = item.data
        table = item.table
        query = (table.deleted != True)
        name = data.get("name")
        if name:
            query &= (table.name.lower() == name.lower())
        code = data.get("code")
        if code:
            query &= (table.code.lower() == code.lower())
        catalog_id = data.get("catalog_id")
        if catalog_id:
            query &= (table.catalog_id == catalog_id)
        parent_category_id = data.get("parent_category_id")
        if parent_category_id:
            query &= (table.parent_category_id == parent_category_id)
        duplicate = current.db(query).select(table.id,
                                             limitby=(0, 1)).first()
        if duplicate:
            item.id = duplicate.id
            item.method = item.METHOD.UPDATE

# =============================================================================
class SupplyItemModel(DataModel):
    """ Supply item descriptions and their links to catalogs """

    names = ("supply_item",
             "supply_catalog_item",
             "supply_item_pack",
             "supply_item_id",
             "supply_item_pack_id",
             "supply_kit_item",
             )

    def model(self):

        T = current.T
        db = current.db
        s3 = current.response.s3
        settings = current.deployment_settings

        # Shortcuts
        add_components = self.add_components
        configure = self.configure
        crud_strings = s3.crud_strings
        define_table = self.define_table

        float_represent = IS_FLOAT_AMOUNT.represent
        translate = settings.get_L10n_translate_supply_item()
        if translate:
            translate_represent = T
        else:
            translate_represent = None

        NONE = current.messages["NONE"]
        YES = T("Yes")

        brand_id = self.supply_brand_id
        catalog_id = self.supply_catalog_id

        item_category_id = self.supply_item_category_id
        item_category_represent = supply_ItemCategoryRepresent(show_catalog = False,
                                                               translate = translate,
                                                               use_code=False,
                                                               )
        item_category_script = '''
$.filterOptionsS3({
 'trigger':'catalog_id',
 'target':'item_category_id',
 'lookupPrefix':'supply',
 'lookupResource':'item_category',
})'''

        # =====================================================================
        # Units of measure
        # - can be adjusted/extended by settings.L10n.units_of_measure
        #
        um = {"pc": T("piece##unit"),
              "pair": T("pair##unit"),
              "set": T("set##unit"),
              "mg": T("mg##unit"),
              "g": T("g##unit"),
              "kg": T("kg##unit"),
              "m": T("m##unit"),
              "ml": T("ml##unit"),
              "L": T("L##unit"),
              }

        l10n_units = settings.get_L10n_units_of_measure()
        if l10n_units:
            um.update(l10n_units)
            um_requires = IS_IN_SET(l10n_units, sort=True)
        else:
            um_requires = IS_IN_SET(um, sort=True)
        um_represent = lambda v, row=None: um.get(v, "-")

        # =====================================================================
        # Supply item
        #
        # - these are catalog descriptions of supply items to be referenced
        #   by item inventories/transactions that specify actual quantities
        #   of such items
        #
        generic_items = settings.get_supply_generic_items()
        use_kits = settings.get_supply_kits()
        track_pack_values = settings.get_supply_track_pack_values()

        tablename = "supply_item"
        define_table(tablename,
                     catalog_id(empty=False),
                     # Needed to auto-create a catalog_item
                     item_category_id(script = item_category_script,
                                      represent = item_category_represent,
                                      ),
                     Field("code", length=16,
                           label = T("Code"),
                           represent = lambda v: v or NONE,
                           requires = IS_LENGTH(16),
                           ),
                     Field("name", length=128, notnull=True,
                           label = T("Name"),
                           represent = translate_represent,
                           requires = [IS_NOT_EMPTY(),
                                       IS_LENGTH(128),
                                       ],
                           ),
                     Field("um", length=16, notnull=True,
                           default = "pc",
                           label = T("Unit of Measure"),
                           represent = um_represent,
                           requires = um_requires,
                           ),

                     # Unit value (for tracking pack values)
                     Field("unit_value", "double",
                           label = T("Value per Unit"),
                           represent = lambda v: \
                                IS_FLOAT_AMOUNT.represent(v, precision=2),
                           readable = track_pack_values,
                           writable = track_pack_values,
                           ),
                     CurrencyField(readable = track_pack_values,
                                   writable = track_pack_values,
                                   ),

                     # Is the item a kit?
                     Field("kit", "boolean",
                           default = False,
                           label = T("Kit?"),
                           represent = lambda opt: YES if opt else NONE,
                           readable = use_kits,
                           writable = use_kits,
                           ),

                     # Manufacturing details (optional)
                     brand_id(
                         readable = not generic_items,
                         writable = not generic_items,
                         ),
                     Field("model", length=128,
                           label = T("Model/Type"),
                           represent = lambda v: v or NONE,
                           requires = IS_LENGTH(128),
                           readable = not generic_items,
                           writable = not generic_items,
                           ),
                     Field("year", "integer",
                           label = T("Year of Manufacture"),
                           represent = lambda v: v or NONE,
                           requires = IS_EMPTY_OR(
                                        IS_INT_IN_RANGE(1900, current.request.now.year + 1)
                                        ),
                           readable = not generic_items,
                           writable = not generic_items,
                           ),

                     Field("obsolete", "boolean",
                           default = False,
                           represent = BooleanRepresent(labels = False,
                                                        # Reverse icons semantics
                                                        icons = (BooleanRepresent.NEG,
                                                                 BooleanRepresent.POS,
                                                                 ),
                                                        flag = True,
                                                        ),
                           readable = False,
                           writable = False,
                           ),
                     CommentsField(),
                     )

        # Components
        add_components(tablename,
                       # Active catalogs
                       supply_catalog = {"name": "active_catalog",
                                         "link": "supply_catalog_item",
                                         "joinby": "item_id",
                                         "key": "catalog_id",
                                         "filterby": {"active": True},
                                         },
                       # Catalog Items
                       supply_catalog_item = "item_id",
                       # Packs
                       supply_item_pack = "item_id",
                       # Inventory Items
                       inv_inv_item = "item_id",
                       # Order Items
                       inv_track_item = "item_id",
                       # Procurement Plan Items
                       proc_plan_item = "item_id",
                       # Request Items
                       req_req_item = "item_id",
                       # Supply Kit Items
                       supply_kit_item = "parent_item_id",
                       # Supply Kit Items (with link table)
                       #supply_item = {"name": "kit_item",
                       #               "link": "supply_kit_item",
                       #               "joinby": "parent_item_id",
                       #               "key": "item_id"
                       #               "actuate": "hide",
                       #               },
                       )

        # Optional components
        if settings.get_supply_use_alt_name():
            add_components(tablename,
                           # Alternative Items
                           supply_item_alt = "item_id",
                           )

        # List Fields
        list_fields = ["name",
                       "code",
                       "um",
                       "catalog_id",
                       "item_category_id",
                       #"kit"
                       #"brand_id"
                       #"model"
                       #"year"
                       #"obsolete"
                       "comments"
                       ]
        if use_kits:
            list_fields[-1:-1] = ["kit"]
        if not generic_items:
            list_fields[-1:-1] = ["brand_id", "model", "year"]

        # Filter Widgets
        text_filter_fields = ["code", "name", "comments"]
        if not generic_items:
            text_filter_fields.append("model")

        filter_widgets = [
            TextFilter(text_filter_fields,
                       label = T("Search"),
                       ),
            # TODO OptionsFilters for catalog/category
            ]

        if not generic_items:
            filter_widgets.extend([
                OptionsFilter("brand_id",
                              represent = "%(name)s",
                              widget = "multiselect",
                              ),
                # TODO this should be a range filter?
                OptionsFilter("year",
                              comment = T("Search for an item by Year of Manufacture."),
                              label = T("Year"),
                              widget = "multiselect",
                              ),
                ])

        # Table configuration
        configure(tablename,
                  deduplicate = self.supply_item_duplicate,
                  filter_widgets = filter_widgets,
                  list_fields = list_fields,
                  onvalidation = self.supply_item_onvalidation,
                  onaccept = self.supply_item_onaccept,
                  orderby = "supply_item.name",
                  )

        # CRUD strings
        ADD_ITEM = T("Create Item")
        crud_strings[tablename] = Storage(
            label_create = ADD_ITEM,
            title_display = T("Item Details"),
            title_list = T("Items"),
            title_update = T("Edit Item"),
            label_list_button = T("List Items"),
            label_delete_button = T("Delete Item##supply"),
            msg_record_created = T("Item added"),
            msg_record_modified = T("Item updated"),
            msg_record_deleted = T("Item deleted"),
            msg_list_empty = T("No Items currently registered"),
            msg_match = T("Matching Items"),
            msg_no_match = T("No Matching Items")
            )


        # Foreign Key Template
        supply_item_represent = supply_ItemRepresent(show_link = True,
                                                     translate = translate,
                                                     )
        supply_item_id = FieldTemplate("item_id",
                                       "reference %s" % tablename,
                                       label = T("Item"),
                                       ondelete = "RESTRICT",
                                       represent = supply_item_represent,
                                       requires = IS_ONE_OF(db, "supply_item.id",
                                                            supply_item_represent,
                                                            sort = True,
                                                            ),
                                       sortby = "name",
                                       widget = S3AutocompleteWidget("supply", "item"),
                                       )

        # =====================================================================
        # Catalog Item
        # - links supply item descriptions to catalogs (many-to-many), i.e.
        #   every item description can appear in multiple catalogs
        #
        tablename = "supply_catalog_item"
        define_table(tablename,
                     catalog_id(),
                     item_category_id(represent = item_category_represent,
                                      script = item_category_script,
                                      ),
                     supply_item_id(script = None), # No Item Pack Filter
                     CommentsField(), # These comments do *not* pull through to an Inventory's Items or a Request's Items
                     )

        # Table configuration
        configure(tablename,
                  deduplicate = self.catalog_item_deduplicate,
                  onaccept = self.catalog_item_onaccept,
                  ondelete = self.catalog_item_ondelete,
                  onvalidation = self.catalog_item_onvalidation,
                  )

        # CRUD strings
        crud_strings[tablename] = Storage(
            label_create = T("Create Catalog Item"),
            title_display = T("Item Catalog Details"),
            title_list = T("Catalog Items"),
            title_update = T("Edit Catalog Item"),
            title_upload = T("Import Catalog Items"),
            label_list_button = T("List Catalog Items"),
            label_delete_button = T("Delete Catalog Item"),
            msg_record_created = T("Catalog Item added"),
            msg_record_modified = T("Catalog Item updated"),
            msg_record_deleted = T("Catalog Item deleted"),
            msg_list_empty = T("No Catalog Items currently registered"),
            msg_match = T("Matching Catalog Items"),
            msg_no_match = T("No Matching Catalog Items")
            )

        # =====================================================================
        # Item Pack
        # - items can be distributed in several different packaging variants
        #
        track_pack_dimensions = settings.get_supply_track_pack_dimensions()

        tablename = "supply_item_pack"
        define_table(tablename,
                     supply_item_id(empty = False),
                     # TODO should reference another table for normalising pack names
                     Field("name", length=128,
                           notnull=True,
                           default = "piece",
                           label = T("Name"),
                           represent = translate_represent,
                           requires = [IS_NOT_EMPTY(),
                                       IS_LENGTH(128),
                                       ],
                           ),
                     Field("quantity", "double", notnull=True,
                           default = 1,
                           label = T("Quantity"),
                           represent = lambda v: float_represent(v, precision=2),
                           ),

                     # Pack value (optional)
                     Field("pack_value", "double",
                           label = T("Value per Pack"),
                           represent = lambda v: \
                                IS_FLOAT_AMOUNT.represent(v, precision=2),
                           readable = track_pack_values,
                           writable = track_pack_values,
                           ),
                     # @ToDo: Move this into a Currency Widget for the pack_value field
                     CurrencyField(readable = track_pack_values,
                                   writable = track_pack_values,
                                   ),

                     # Pack dimensions (optional)
                     Field("weight", "double",
                           label = T("Weight (kg)"),
                           represent = lambda v: \
                                       float_represent(v, precision=2),
                           requires = IS_EMPTY_OR(IS_FLOAT_AMOUNT(minimum=0.0)),
                           readable = track_pack_dimensions,
                           writable = track_pack_dimensions,
                           ),
                     Field("length", "double",
                           label = T("Length (m)"),
                           represent = lambda v: \
                                       float_represent(v, precision=2),
                           requires = IS_EMPTY_OR(IS_FLOAT_AMOUNT(minimum=0.0)),
                           readable = track_pack_dimensions,
                           writable = track_pack_dimensions,
                           ),
                     Field("width", "double",
                           label = T("Width (m)"),
                           represent = lambda v: \
                                       float_represent(v, precision=2),
                           requires = IS_EMPTY_OR(IS_FLOAT_AMOUNT(minimum=0.0)),
                           readable = track_pack_dimensions,
                           writable = track_pack_dimensions,
                           ),
                     Field("height", "double",
                           label = T("Height (m)"),
                           represent = lambda v: \
                                       float_represent(v, precision=2),
                           requires = IS_EMPTY_OR(IS_FLOAT_AMOUNT(minimum=0.0)),
                           readable = track_pack_dimensions,
                           writable = track_pack_dimensions,
                           ),
                     Field("volume", "double",
                           label = T("Volume (m3)"),
                           represent = lambda v: \
                                       float_represent(v, precision=3),
                           requires = IS_EMPTY_OR(IS_FLOAT_AMOUNT(minimum=0.0)),
                           readable = track_pack_dimensions,
                           writable = track_pack_dimensions,
                           ),

                     CommentsField(),
                     )

        # Components
        add_components(tablename,
                       # Inventory Items
                       inv_inv_item = "item_pack_id",
                       )

        # List fields
        list_fields = ["item_id",
                       "name",
                       "quantity",
                       "item_id$um",
                       "comments",
                       ]
        if track_pack_values:
            list_fields[-1:-1] = ["value", "currency"]
        if track_pack_dimensions:
            list_fields[-1:-1] = ["weight", "length", "width", "height", "volume"]

        # Table configuration
        configure(tablename,
                  deduplicate = self.supply_item_pack_duplicate,
                  list_fields = list_fields,
                  )

        # CRUD strings
        ADD_ITEM_PACK = T("Create Item Pack")
        crud_strings[tablename] = Storage(
            label_create = ADD_ITEM_PACK,
            title_display = T("Item Pack Details"),
            title_list = T("Item Packs"),
            title_update = T("Edit Item Pack"),
            label_list_button = T("List Item Packs"),
            label_delete_button = T("Delete Item Pack"),
            msg_record_created = T("Item Pack added"),
            msg_record_modified = T("Item Pack updated"),
            msg_record_deleted = T("Item Pack deleted"),
            msg_list_empty = T("No Item Packs currently registered"))

        # Foreign Key Template
        item_pack_represent = supply_ItemPackRepresent(lookup = "supply_item_pack",
                                                       translate = translate,
                                                       )
        item_pack_id = FieldTemplate("item_pack_id", "reference %s" % tablename,
                                     label = T("Pack"),
                                     ondelete = "RESTRICT",
                                     represent = item_pack_represent,
                                     # Do not display any packs initially
                                     # will be populated by filterOptionsS3
                                     requires = IS_ONE_OF_EMPTY_SELECT(db, "supply_item_pack.id",
                                                                       item_pack_represent,
                                                                       sort=True,
                                                                       # @ToDo: Enforce "Required" for imports
                                                                       # @ToDo: Populate based on item_id in controller instead of IS_ONE_OF_EMPTY_SELECT
                                                                       # filterby = "item_id",
                                                                       # filter_opts = (....),
                                                                       ),
                                     # Using EmptyOptionsWidget to pass the previously
                                     # selected option to filterOptionsS3
                                     widget = EmptyOptionsWidget.widget,
                                     script = '''
$.filterOptionsS3({
 'trigger':'item_id',
 'target':'item_pack_id',
 'lookupPrefix':'supply',
 'lookupResource':'item_pack',
 'msgNoRecords':i18n.no_packs,
 'fncPrep':S3.supply.fncPrepItem,
 'fncRepresent':S3.supply.fncRepresentItem
})''',
                                     sortby = "name",
                                     )

        # =====================================================================
        # Supply Kit Item Table
        # - for defining what items are in a kit
        #
        tablename = "supply_kit_item"
        define_table(tablename,
                     supply_item_id("parent_item_id",
                                    label = T("Parent Item"),
                                    comment = None,
                                    ),
                     supply_item_id("item_id",
                                    label = T("Kit Item"),
                                    ),
                     Field("quantity", "double",
                           label = T("Quantity"),
                           represent = lambda v: \
                                       float_represent(v, precision=2),
                           ),
                     item_pack_id(),
                     CommentsField(),
                     )

        # CRUD strings
        crud_strings[tablename] = Storage(
            label_create = T("Add Item to Kit"),
            title_display = T("Kit Item Details"),
            title_list = T("Kit Items"),
            title_update = T("Edit Kit Item"),
            label_list_button = T("List Kit Items"),
            label_delete_button = T("Remove Item from Kit"),
            msg_record_created = T("Item added to Kit"),
            msg_record_modified = T("Kit Item updated"),
            msg_record_deleted = T("Item removed from Kit"),
            msg_list_empty = T("No Items currently in this Kit"))

        # ---------------------------------------------------------------------
        # Pass names back to global scope (s3.*)
        #
        return {"supply_item_id": supply_item_id,
                "supply_item_pack_id": item_pack_id,
                "supply_item_represent": supply_item_represent,
                "supply_item_pack_quantity": SupplyItemPackQuantity,
                "supply_item_add": self.supply_item_add,
                "supply_item_pack_represent": item_pack_represent,
                }

    # -------------------------------------------------------------------------
    def defaults(self):
        """ Return safe defaults for names in case the model is disabled """

        dummy = FieldTemplate.dummy

        return {"supply_item_id": dummy("item_id"),
                "supply_item_pack_id": dummy("item_pack_id"),
                "supply_item_pack_quantity": lambda tablename: lambda row: 0,
                }

    # -------------------------------------------------------------------------
    @staticmethod
    def supply_item_onvalidation(form):
        """
            Form validation of supply item
            - item code/name must be unique within local catalogs (i.e. all
              catalogs of the same organisation)
            - item code/name must not match global items (i.e. items not
              linked to any catalog, or to not organisation-specific catalogs)

            Args:
                form: the FORM
        """

        T = current.T
        db = current.db
        s3db = current.s3db

        table = s3db.supply_item
        ctable = s3db.supply_catalog

        # Get form record ID
        record_id = get_form_record_id(form)

        # Get form record data
        data = get_form_record_data(form, table, ["catalog_id", "code", "name"])
        catalog_id = data.get("catalog_id")
        code = data.get("code")
        name = data.get("name")

        # Organisation the catalog belongs to
        organisation_id = None
        if catalog_id:
            catalog = db(ctable.id == catalog_id).select(ctable.organisation_id,
                                                         limitby = (0, 1),
                                                         ).first()
            if catalog:
                organisation_id = catalog.organisation_id

        # Items in relevant catalogs
        query = (ctable.organisation_id == None)
        if organisation_id:
            query |= (ctable.organisation_id == organisation_id)
        query &= (ctable.deleted == False)
        catalog_set = db(query)._select(ctable.id)
        is_relevant_item = (table.catalog_id == None) | \
                           (table.catalog_id.belongs(catalog_set))

        # Check for code duplicates
        if code:
            query = is_relevant_item & \
                    (table.code == code) & \
                    (table.deleted == False)
            if record_id:
                query = (table.id != record_id) & query
            row = db(query).select(table.id, limitby=(0, 1)).first()
            if row:
                form.errors["code"] = T("Item with code %(code)s already exists") % {"code": code}

        # Check for name duplicates
        if name:
            query = is_relevant_item & \
                    (table.name == name) & \
                    (table.deleted == False)
            if record_id:
                query = (table.id != record_id) & query
            row = db(query).select(table.id, limitby=(0, 1)).first()
            if row:
                form.errors["name"] = T("Item with name %(name)s already exists") % {"name": name}

    # -------------------------------------------------------------------------
    @staticmethod
    def supply_item_onaccept(form):
        """
            Create a catalog_item for this item
            Update the UM (Unit of Measure) in the supply_item_pack table
        """

        db = current.db
        s3db = current.s3db

        sitable = s3db.supply_item
        citable = s3db.supply_catalog_item

        form_vars = form.vars
        item_id = form_vars.id

        item_category_id = form_vars.get("item_category_id")

        catalog_id = None
        if "catalog_id" in form_vars:
            catalog_id = form_vars.catalog_id
        elif item_category_id:
            # Look up the catalog from the category
            ictable = s3db.supply_item_category
            query = (ictable.id == item_category_id) & \
                    (ictable.deleted == False)
            row = db(query).select(ictable.catalog_id,
                                   limitby = (0, 1),
                                   ).first()
            if row:
                catalog_id = row.catalog_id
        if not catalog_id:
            # Check for default catalog
            catalog_id = sitable.catalog_id.default

        # Look up existing catalog item, if one exists
        query = (citable.item_id == item_id) & \
                (citable.deleted == False)
        rows = db(query).select(citable.id)
        if not len(rows):
            # Create new catalog item
            catalog_item = {"catalog_id": catalog_id,
                            "item_category_id": item_category_id,
                            "item_id": item_id,
                            }
            catalog_item["id"] = citable.insert(**catalog_item)
            current.auth.s3_set_record_owner(citable, catalog_item)
            s3db.onaccept(citable, catalog_item, method="create")

        elif len(rows) == 1:
            # Update the existing catalog item if the catalog/category has
            # changed (if there is only one catalog item)
            catalog_item = rows.first()
            catalog_item.update_record(catalog_id = catalog_id,
                                       item_category_id = item_category_id,
                                       item_id = item_id,
                                       )
            #current.auth.s3_set_record_owner(citable, catalog_item, force_update=True)

        # Update UM
        um = form_vars.um or sitable.um.default
        um_repr = s3_str(sitable.um.represent(um)) if um else None
        if um_repr:
            ptable = db.supply_item_pack
            query = (ptable.item_id == item_id) & \
                    (ptable.quantity == 1.0) & \
                    (ptable.deleted == False)
            if db(query).update(name=um_repr) == 0:
                # Create a new item packet
                ptable.insert(item_id=item_id, name=um_repr, quantity=1.0)

        if form_vars.kit:
            # Go to that tab afterwards
            url = URL(args = ["[id]", "kit_item"])
            current.s3db.configure("supply_item",
                                   create_next = url,
                                   update_next = url,
                                   )

    # -------------------------------------------------------------------------
    @staticmethod
    def catalog_item_onvalidation(form):
        """
            Form validation of catalog items
            - same item can be added only once to a catalog
            - item code and name must be unique within a catalog

            Args:
                form: the FORM
        """

        T = current.T
        db = current.db
        s3db = current.s3db

        table = s3db.supply_catalog_item

        # Get form record ID
        record_id = get_form_record_id(form)

        # Field to show errors on
        fn = "item_id" if "item_id" in form.vars else "catalog_id"

        # Get form record data
        data = get_form_record_data(form, table, ["catalog_id", "item_id"])
        catalog_id = data.get("catalog_id")
        item_id = data.get("item_id")

        # Check if item already linked to this catalog
        query = (table.catalog_id == catalog_id) & \
                (table.item_id == item_id) & \
                (table.deleted == False)
        if record_id:
            query = (table.id != record_id) & query
        row = db(query).select(table.id, limitby=(0, 1)).first()
        if row:
            form.errors[fn] = T("Item already in catalog")
            return

        # Get item code and name
        itable = s3db.supply_item
        item = db(itable.id == item_id).select(itable.code,
                                               itable.name,
                                               limitby = (0, 1),
                                               ).first()
        if item:
            # Check if the catalog already has an item with the same code or name
            query = (table.catalog_id == catalog_id) & \
                    (table.deleted == False)
            if record_id:
                query = (table.id != record_id)

            for k in ("code", "name"):
                if not item[k]:
                    continue
                join = itable.on((itable.id == table.item_id) & \
                                 (itable[k] == item[k]))
                row = db(query).select(table.id, join=join, limitby=(0, 1)).first()
                if row:
                    form.errors[fn] = T("An item with the same code or name already exists in catalog")
                    break

    # -------------------------------------------------------------------------
    @classmethod
    def catalog_item_onaccept(cls, form):
        """
            Onaccept of catalog item:
            - handle possible removal from original catalog
        """

        table = current.s3db.supply_catalog_item

        data = get_form_record_data(form, table, ["item_id"])
        item_id = data.get("item_id")

        cls.supply_item_update_catalog(item_id)

    # -------------------------------------------------------------------------
    @classmethod
    def catalog_item_ondelete(cls, row):
        """
            Ondelete of catalog item:
            - handle possible removal from original catalog
        """

        cls.supply_item_update_catalog(row.item_id)

    # -------------------------------------------------------------------------
    @staticmethod
    def supply_item_add(quantity_1, pack_quantity_1,
                        quantity_2, pack_quantity_2):
        """
            Adds item quantities together, accounting for different pack
            quantities.
            Returned quantity according to pack_quantity_1

            Used by controllers/inv.py & modules/s3db/inv.py
        """

        if pack_quantity_1 == pack_quantity_2:
            # Faster calculation
            quantity = quantity_1 + quantity_2
        else:
            quantity = ((quantity_1 * pack_quantity_1) +
                        (quantity_2 * pack_quantity_2)) / pack_quantity_1
        return quantity

    # -------------------------------------------------------------------------
    @staticmethod
    def supply_item_update_catalog(item_id):
        """
            Make sure there always is a catalog item for the original
            catalog/category of a supply item

            Args:
                item_id: the supply item ID
        """

        db = current.db
        s3db = current.s3db

        table = s3db.supply_item
        ctable = s3db.supply_catalog
        citable = s3db.supply_catalog_item

        # Look up the original catalog/category of the supply item
        query = (table.id == item_id) & (table.deleted==False)
        item = db(query).select(table.id,
                                table.catalog_id,
                                table.item_category_id,
                                limitby = (0, 1),
                                ).first()

        if item and item.catalog_id:
            # Check if a catalog item for this original catalog still exists
            query = (citable.item_id == item.id) & \
                    (citable.catalog_id == item.catalog_id) & \
                    (citable.deleted == False)
            row = db(query).select(citable.id, limitby=(0, 1)).first()
            if not row:
                # Item has been removed from its original catalog

                # Look up the organisation_id of the original catalog
                query = (ctable.id == item.catalog_id) & \
                        (ctable.deleted == False)
                catalog = db(query).select(ctable.organisation_id,
                                           limitby= (0, 1),
                                           ).first()
                organisation_id = catalog.organisation_id if catalog else None

                # All other catalogs of the same organisation
                query = (ctable.organisation_id == organisation_id) & \
                        (ctable.deleted == False)
                catalogs = db(query)._select(ctable.id)

                # Check if the item is still linked to another catalog of this
                # organisation
                query = (citable.item_id == item.id) & \
                        (citable.catalog_id.belongs(catalogs)) & \
                        (citable.deleted == False)
                citem = db(query).select(citable.catalog_id,
                                         citable.item_category_id,
                                         limitby = (0, 1),
                                         orderby = citable.created_on,
                                         ).first()
                if citem:
                    # Yes: update the original catalog/category from this link
                    item.update_record(catalog_id = citem.catalog_id,
                                       item_category_id = citem.item_category_id,
                                       modified_on = table.modified_on,
                                       modified_by = table.modified_by,
                                       )
                else:
                    # No: restore the original catalog item
                    citem = {"item_id": item.id,
                             "catalog_id": item.catalog_id,
                             "item_category_id": item.item_category_id,
                             }
                    citem_id = citem["id"] = citable.insert(**citem)
                    s3db.update_super(citable, citem)
                    current.auth.s3_set_record_owner(citable, citem_id)
                    # No onaccept to avoid infinite recursion

                    # Warning to the user
                    current.response.warning = current.T("Catalog Item restored")

    # -------------------------------------------------------------------------
    @staticmethod
    def supply_item_duplicate(item):
        """
            Callback function used to look for duplicates during
            the import process

            Args:
                item: the ImportItem to check
        """

        data = item.data
        code = data.get("code")
        if code:
            # Same Code => definitely duplicate
            table = item.table
            query = (table.deleted != True) & \
                    (table.code.lower() == code.lower())
            duplicate = current.db(query).select(table.id,
                                                 limitby=(0, 1)).first()
            if duplicate:
                item.id = duplicate.id
                item.method = item.METHOD.UPDATE
                return
        else:
            name = data.get("name")
            if not name:
                # No way to match
                return
            um = data.get("um")
            if not um:
                # Try to extract UM from Name
                name, um = item_um_from_name(name)
            table = item.table
            query = (table.deleted != True) & \
                    (table.name.lower() == name.lower())
            if um:
                query &= (table.um.lower() == um.lower())
            catalog_id = data.get("catalog_id")
            if catalog_id:
                query &= (table.catalog_id == catalog_id)

            duplicate = current.db(query).select(table.id,
                                                 limitby=(0, 1)).first()
            if duplicate:
                item.id = duplicate.id
                item.method = item.METHOD.UPDATE

    # -------------------------------------------------------------------------
    @staticmethod
    def supply_item_pack_duplicate(item):
        """
            Callback function used to look for duplicates during
            the import process

            Args:
                item: the ImportItem to check
        """

        data = item.data
        table = item.table
        query = (table.deleted != True)
        name = data.get("name")
        if name:
            query &= (table.name.lower() == name.lower())
        item_id = data.get("item_id")
        if item_id:
            query &= (table.item_id == item_id)
        quantity = data.get("quantity")
        if quantity:
            query &= (table.quantity == quantity)
        duplicate = current.db(query).select(table.id,
                                             limitby = (0, 1)
                                             ).first()
        if duplicate:
            item.id = duplicate.id
            item.method = item.METHOD.UPDATE

    # -------------------------------------------------------------------------
    @staticmethod
    def catalog_item_deduplicate(item):
        """
            Callback function used to look for duplicates during
            the import process

            Args:
                item: the ImportItem to check
        """

        data = item.data
        table = item.table
        query = (table.deleted != True)
        item_id = data.get("item_id")
        if item_id:
            query &= (table.item_id == item_id)
        catalog_id = data.get("catalog_id")
        if catalog_id:
            query &= (table.catalog_id == catalog_id)
        item_category_id = data.get("item_category_id")
        if item_category_id:
            query &= (table.item_category_id == item_category_id)
        duplicate = current.db(query).select(table.id,
                                             limitby=(0, 1)).first()
        if duplicate:
            item.id = duplicate.id
            item.method = item.METHOD.UPDATE

# =============================================================================
class SupplyItemEntityModel(DataModel):

    names = ("supply_item_entity",
             "supply_item_entity_id",
             )

    def model(self):

        T = current.T

        # Shortcuts
        configure = self.configure
        super_link = self.super_link

        supply_item_id = self.supply_item_id
        item_pack_id = self.supply_item_pack_id

        # =====================================================================
        # Item Super-Entity
        #
        # This super entity provides a common way to provide a foreign key to supply_item
        # - it allows searching/reporting across Item types easily.
        #
        item_types = Storage(asset_asset = T("Asset"),
                             asset_item = T("Asset Item"),
                             inv_inv_item = T("Warehouse Stock"),
                             inv_track_item = T("Order Item"),
                             proc_plan_item = T("Planned Procurement Item"),
                             )

        tablename = "supply_item_entity"
        self.super_entity(tablename, "item_entity_id", item_types,
                          supply_item_id(),
                          item_pack_id(),
                          Field("quantity", "double", notnull=True,
                                default = 1.0,
                                label = T("Quantity"),
                                ),
                          *MetaFields.owner_meta_fields())

        # Foreign Key Template
        item_id = lambda: super_link("item_entity_id", "supply_item_entity")

        # Filter Widgets
        filter_widgets = [
            TextFilter(name = "item_entity_search_text",
                       label = T("Search"),
                       comment = T("Search for an item by text."),
                       field = ["item_id$name",
                                #"item_id$item_category_id$name",
                                #"site_id$name"
                                ]
                       ),
            OptionsFilter("item_id$item_category_id",
                          label = T("Code Share"),
                          comment = T("If none are selected, then all are searched."),
                          #represent = "%(name)s",
                          cols = 2,
                          ),
        ]

        # Configuration
        configure(tablename,
                  filter_widgets = filter_widgets,
                  )

        # ---------------------------------------------------------------------
        # Pass names back to global scope (s3.*)
        #
        return {"supply_item_entity_id": item_id,
                }

    # -------------------------------------------------------------------------
    def defaults(self):
        """ Return safe defaults for names in case the model is disabled """

        dummy = FieldTemplate.dummy

        return {"supply_item_entity_id": dummy("item_entity_id"),
                }

# =============================================================================
class SupplyItemAlternativesModel(DataModel):

    names = ("supply_item_alt",
             )

    def model(self):

        T = current.T
        s3 = current.response.s3

        # Shortcuts
        crud_strings = s3.crud_strings
        define_table = self.define_table

        float_represent = IS_FLOAT_AMOUNT.represent

        supply_item_id = self.supply_item_id

        # =====================================================================
        # Alternative Items
        #
        #  If the desired item isn't found, then these are designated as
        #  suitable alternatives
        #
        tablename = "supply_item_alt"
        define_table(tablename,
                     supply_item_id(notnull=True),
                     Field("quantity", "double", notnull=True,
                           default = 1,
                           label = T("Quantity"),
                           represent = lambda v: \
                                       float_represent(v, precision=2),
                           comment = DIV(_title = "%s|%s" % \
                                                  (T("Quantity"),
                                                   T("The number of Units of Measure of the Alternative Items which is equal to One Unit of Measure of the Item"),
                                                   ),
                                         _class = "tooltip",
                                         ),
                           ),
                     supply_item_id("alt_item_id",
                                    notnull=True,
                                    comment = PopupLink(c = "supply",
                                                        f = "item",
                                                        label = T("Create Item"),
                                                        title = T("Item"),
                                                        tooltip = T("Type the name of an existing catalog item OR Click 'Create Item' to add an item which is not in the catalog."),
                                                        vars = {"child": "alt_item_id"
                                                                },
                                                        ),
                                    ),
                     CommentsField(),
                     )

        # CRUD strings
        crud_strings[tablename] = Storage(
            label_create = T("Create Alternative Item"),
            title_display = T("Alternative Item Details"),
            title_list = T("Alternative Items"),
            title_update = T("Edit Alternative Item"),
            label_list_button = T("List Alternative Items"),
            label_delete_button = T("Delete Alternative Item"),
            msg_record_created = T("Alternative Item added"),
            msg_record_modified = T("Alternative Item updated"),
            msg_record_deleted = T("Alternative Item deleted"),
            msg_list_empty = T("No Alternative Items currently registered"))

        # ---------------------------------------------------------------------
        # Pass names back to global scope (s3.*)
        #
        return None

    # -------------------------------------------------------------------------
    def defaults(self):
        """ Return safe defaults for names in case the model is disabled """

        return None

# =============================================================================
class SupplyItemBrandModel(DataModel):

    names = ("supply_brand",
             "supply_brand_id",
             )

    def model(self):

        T = current.T
        db = current.db
        s3 = current.response.s3

        # Shortcuts
        crud_strings = s3.crud_strings
        define_table = self.define_table

        # =====================================================================
        # Brand
        #
        tablename = "supply_brand"
        define_table(tablename,
                     Field("name", length=128, notnull=True, unique=True,
                           label = T("Name"),
                           requires = [IS_NOT_EMPTY(),
                                       IS_LENGTH(128),
                                       IS_NOT_ONE_OF(db,
                                                     "%s.name" % tablename,
                                                     ),
                                       ],
                           ),
                     CommentsField(),
                     )

        # CRUD strings
        ADD_BRAND = T("Create Brand")
        crud_strings[tablename] = Storage(
            label_create = ADD_BRAND,
            title_display = T("Brand Details"),
            title_list = T("Brands"),
            title_update = T("Edit Brand"),
            label_list_button = T("List Brands"),
            label_delete_button = T("Delete Brand"),
            msg_record_created = T("Brand added"),
            msg_record_modified = T("Brand updated"),
            msg_record_deleted = T("Brand deleted"),
            msg_list_empty = T("No Brands currently registered"))

        # Foreign Key Template
        # TODO Drop add-link?
        represent = S3Represent(lookup=tablename)
        brand_id = FieldTemplate("brand_id", "reference %s" % tablename,
                                 label = T("Brand"),
                                 ondelete = "RESTRICT",
                                 represent = represent,
                                 requires = IS_EMPTY_OR(
                                                IS_ONE_OF(db, "supply_brand.id",
                                                          represent,
                                                          sort = True,
                                                          )),
                                  sortby = "name",
                                  comment = PopupLink(c = "supply",
                                                      f = "brand",
                                                      label = ADD_BRAND,
                                                      title = T("Brand"),
                                                      tooltip = T("The list of Brands are maintained by the Administrators."),
                                                      ),
                                  )

        # ---------------------------------------------------------------------
        # Pass names back to global scope (s3.*)
        #
        return {"supply_brand_id": brand_id,
                }

    # -------------------------------------------------------------------------
    def defaults(self):
        """ Return safe defaults for names in case the model is disabled """

        dummy = FieldTemplate.dummy

        return {"supply_brand_id": dummy("brand_id"),
                }

# =============================================================================
class SupplyPersonModel(DataModel):
    """
        Link table between People & Items
        - e.g. Donations
    """

    names = ("supply_person_item",
             "supply_person_item_status",
             )

    def model(self):

        T = current.T
        crud_strings = current.response.s3.crud_strings
        define_table = self.define_table

        # ---------------------------------------------------------------------
        # Person Item Status
        #
        tablename = "supply_person_item_status"
        define_table(tablename,
                     Field("name", length=128, notnull=True, unique=True,
                           label = T("Name"),
                           requires = [IS_NOT_EMPTY(),
                                       IS_LENGTH(128),
                                       ],
                           ),
                     CommentsField(),
                     )

        crud_strings[tablename] = Storage(
            label_create = T("Add Status"),
            title_display = T("Status Details"),
            title_list = T("Statuses"),
            title_update = T("Edit Status"),
            #title_upload = T("Import Statuses"),
            label_list_button = T("List Statuses"),
            label_delete_button = T("Remove Status"),
            msg_record_created = T("Status added"),
            msg_record_modified = T("Status updated"),
            msg_record_deleted = T("Status removed"),
            msg_list_empty = T("No Statuses currently defined")
        )

        # Foreign Key Template
        represent = S3Represent(lookup = tablename)
        status_id = FieldTemplate("status_id", "reference %s" % tablename,
                                  label = T("Status"),
                                  ondelete = "SET NULL",
                                  represent = represent,
                                  requires = IS_EMPTY_OR(
                                                IS_ONE_OF(current.db,
                                                          "%s.id" % tablename,
                                                          represent,
                                                          )),
                                  )

        # ---------------------------------------------------------------------
        # Link table between People & Items
        #
        tablename = "supply_person_item"
        define_table(tablename,
                     self.supply_item_id(comment = None,
                                         empty = False,
                                         ondelete = "CASCADE",
                                         widget = None, # Dropdown not AC
                                         ),
                     self.pr_person_id(empty = False,
                                       ondelete = "CASCADE",
                                       ),
                     status_id(), # empty = False (in templates as-required)
                     # Requested By / Taken By
                     self.org_organisation_id(ondelete = "SET NULL",
                                              ),
                     CommentsField(comment = None),
                     )

        crud_strings[tablename] = Storage(
            label_create = T("Add Item"),
            title_display = T("Item Details"),
            title_list = T("Items"),
            title_update = T("Edit Item"),
            #title_upload = T("Import Items"),
            label_list_button = T("List Items"),
            label_delete_button = T("Remove Item"),
            msg_record_created = T("Item added"),
            msg_record_modified = T("Item updated"),
            msg_record_deleted = T("Item removed"),
            msg_list_empty = T("No Items currently registered for this person")
        )

        self.configure(tablename,
                       deduplicate = S3Duplicate(primary = ("item_id",
                                                            "person_id",
                                                            ),
                                                 ),
                       )

        # Pass names back to global scope (s3.*)
        return None

# =============================================================================
class SupplyDistributionModel(DataModel):
    """ Model to register supply item distributions to beneficiaries """

    names = ("supply_distribution_set",
             "supply_distribution_set_id",
             "supply_distribution_set_item",
             "supply_distribution",
             "supply_distribution_item",
             )

    def model(self):

        T = current.T
        db = current.db

        s3 = current.response.s3
        crud_strings = s3.crud_strings
        settings = current.deployment_settings

        define_table = self.define_table
        super_link = self.super_link
        add_components = self.add_components
        configure = self.configure

        organisation_id = self.org_organisation_id
        supply_item_id = self.supply_item_id
        supply_item_pack_id = self.supply_item_pack_id

        check_resident = settings.get_supply_distribution_check_resident()
        site_represent = self.org_SiteRepresent(show_type=False)

        # ---------------------------------------------------------------------
        # Distribution Modes
        #
        set_modes = (("GRA", T("Grant##distribution")),
                     ("LOA", T("Loan##distribution")),
                     ("RET", T("Return##distribution")),
                     )
        dist_modes = set_modes + \
                     (("LOS", T("Loss##distribution")),
                      )

        mode_represent = S3PriorityRepresent(dist_modes, {"GRA": "blue",
                                                          "LOA": "amber",
                                                          "RET": "green",
                                                          "LOS": "black",
                                                          }).represent

        # ---------------------------------------------------------------------
        # Distribution item set
        # - set of items to be distributed to beneficiaries
        #
        tablename = "supply_distribution_set"
        define_table(tablename,
                     organisation_id(
                         comment = None,
                         ),
                     Field("name",
                           label = T("Title"),
                           requires = [IS_NOT_EMPTY(), IS_LENGTH(512, minsize=1)],
                           ),
                     Field("max_per_day", "integer",
                           label = T("Maximum Number per Day"),
                           requires = IS_EMPTY_OR(IS_INT_IN_RANGE(1, None)),
                           comment = T("Maximum number of distributions per client and day"),
                           ),
                     Field("min_interval", "double",
                           label = T("Minimum Interval (Hours)"),
                           requires = IS_EMPTY_OR(IS_FLOAT_IN_RANGE(0.0, None)),
                           widget = S3HoursWidget(precision=2),
                           comment = T("Minimum time interval between two consecutive distributions to the same client"),
                           ),
                     Field("residents_only", "boolean",
                           label = T("Current residents only"),
                           default = True,
                           represent = BooleanRepresent(labels = False,
                                                        icons = True,
                                                        colors = True,
                                                        flag = True,
                                                        ),
                           comment = T("Distribution requires that the person is checked-in at a shelter"),
                           readable = check_resident,
                           writable = check_resident,
                           ),
                     Field("active", "boolean",
                           label = T("Active"),
                           default = True,
                           represent = BooleanRepresent(icons = True,
                                                        colors = True,
                                                        ),
                           comment = T("Registration is currently permitted"),
                           ),
                     CommentsField(),
                     )

        # Components
        add_components(tablename,
                       supply_distribution_set_item = "distribution_set_id",
                       dvr_case_flag = ({"name": "flag_required",
                                         "link": "dvr_distribution_flag_required",
                                         "joinby": "distribution_set_id",
                                         "key": "flag_id",
                                         },
                                        {"name": "flag_debarring",
                                         "link": "dvr_distribution_flag_debarring",
                                         "joinby": "distribution_set_id",
                                         "key": "flag_id",
                                         },
                                        ),
                       )

        # Filter widgets
        filter_widgets = [TextFilter(["name", "comments"],
                                     label = T("Search"),
                                     ),
                          OptionsFilter("active",
                                        options = OrderedDict([(True, T("Yes")),
                                                               (False, T("No")),
                                                               ]),
                                        default = True,
                                        cols = 2,
                                        ),
                          ]

        # Table configuration
        configure(tablename,
                  filter_widgets = filter_widgets,
                  onvalidation = self.distribution_set_onvalidation,
                  realm_components = ("distribution_set_item",),
                  update_realm = True,
                  )

        # CRUD strings
        crud_strings[tablename] = Storage(
            label_create = T("Create Distribution Item Set"),
            title_display = T("Distribution Item Set"),
            title_list = T("Distribution Item Sets"),
            title_update = T("Edit Distribution Item Set"),
            label_list_button = T("List Distribution Item Sets"),
            label_delete_button = T("Delete Distribution Item Set"),
            msg_record_created = T("Distribution Item Set added"),
            msg_record_modified = T("Distribution Item Set updated"),
            msg_record_deleted = T("Distribution Item Set deleted"),
            msg_list_empty = T("No Distribution Item Sets currently registered"),
            )

        # Field template
        represent = S3Represent(lookup=tablename)
        distribution_set_id = FieldTemplate("distribution_set_id",
                                            "reference %s" % tablename,
                                            label = T("Distribution Item Set"),
                                            represent = represent,
                                            requires = IS_EMPTY_OR(
                                                        IS_ONE_OF(db, "%s.id" % tablename,
                                                                  represent,
                                                                  )),
                                            sortby = "name",
                                            )

        # ---------------------------------------------------------------------
        # Distribution set item
        #
        tablename = "supply_distribution_set_item"
        define_table(tablename,
                     distribution_set_id(
                         ondelete = "CASCADE",
                         ),
                     Field("mode",
                           label = T("Mode"),
                           default = "GRA",
                           represent = mode_represent,
                           requires = IS_IN_SET(set_modes,
                                                sort = False,
                                                zero = None,
                                                ),
                           ),
                     supply_item_id(
                         comment = None,
                         ),
                     supply_item_pack_id(),
                     Field("quantity", "integer",
                           label = T("Quantity"),
                           default = 1,
                           requires = IS_INT_IN_RANGE(1),
                           ),
                     Field("quantity_max", "integer",
                           label = T("Maximum Quantity"),
                           requires = IS_EMPTY_OR(IS_INT_IN_RANGE(1)),
                           ),
                     )

        # List fields
        # - including catalog status
        list_fields = ["mode",
                       "item_id",
                       "item_pack_id",
                       "quantity",
                       "quantity_max",
                       (T("Catalog"), "item_id$catalog_item.catalog_id"),
                       "item_id$active_catalog.active",
                       ]

        # Table configuration
        configure(tablename,
                  list_fields = list_fields,
                  onvalidation = self.distribution_set_item_onvalidation,
                  )

        # CRUD strings
        crud_strings[tablename] = Storage(
            label_create = T("Add Item"),
            title_display = T("Item Details"),
            title_list = T("Items"),
            title_update = T("Edit Item"),
            label_list_button = T("List Items"),
            label_delete_button = T("Delete Item##supply"),
            msg_record_created = T("Item added"),
            msg_record_modified = T("Item updated"),
            msg_record_deleted = T("Item deleted"),
            msg_list_empty = T("No Items currently registered"),
            )

        # ---------------------------------------------------------------------
        # Distribution
        # - an actual distribution event
        #
        tablename = "supply_distribution"
        define_table(tablename,
                     organisation_id(
                         comment = None,
                         ),
                     distribution_set_id(
                         ondelete = "SET NULL",
                         readable=False,
                         writable=False,
                         ),
                     super_link("site_id", "org_site",
                                label = T("Place"),
                                represent = site_represent,
                                ),
                     DateTimeField(
                         default="now",
                         ),
                     self.pr_person_id(
                         label = T("Recipient"),
                         ),
                     self.hrm_human_resource_id(
                         label = T("Staff Member in Charge"),
                         ),
                     )

        # Components
        add_components(tablename,
                       supply_distribution_item = "distribution_id",
                       )

        # Table configuration
        configure(tablename,
                  realm_components = ("distribution_item",),
                  update_realm = True,
                  )

        # Method for distribution registration
        self.set_method(tablename,
                        method = "register",
                        action = Distribution,
                        )

        # CRUD strings
        crud_strings[tablename] = Storage(
            label_create = T("Register Distribution"),
            title_display = T("Distribution"),
            title_list = T("Distributions"),
            title_update = T("Edit Distribution"),
            label_list_button = T("List Distributions"),
            label_delete_button = T("Delete Distribution"),
            msg_record_created = T("Distribution registered"),
            msg_record_modified = T("Distribution updated"),
            msg_record_deleted = T("Distribution deleted"),
            msg_list_empty = T("No Distributions currently registered"),
            )

        # ---------------------------------------------------------------------
        # Distribution Item
        #
        tablename = "supply_distribution_item"
        define_table(tablename,
                     Field("distribution_id", "reference supply_distribution",
                           label = T("Distribution"),
                           readable = False,
                           writable = False,
                           ),
                     self.pr_person_id(
                         readable = False,
                         writable = False,
                         ),
                     Field("mode",
                           label = T("Mode"),
                           default = "GRA",
                           represent = mode_represent,
                           requires = IS_IN_SET(dist_modes,
                                                sort = False,
                                                zero = None,
                                                ),
                           ),
                     supply_item_id(
                         comment = None,
                         ),
                     supply_item_pack_id(),
                     Field("quantity", "integer",
                           label = T("Quantity"),
                           default = 0,
                           requires = IS_INT_IN_RANGE(0),
                           ),
                     )

        # Standard list fields
        list_fields = ["distribution_id$date",
                       "mode",
                       "item_id",
                       "item_pack_id",
                       "quantity",
                       ]

        # Table configuration
        configure(tablename,
                  list_fields = list_fields,
                  onaccept = self.distribution_item_onaccept,
                  orderby = "supply_distribution.date desc",
                  )

        # CRUD Strings
        crud_strings[tablename] = crud_strings["supply_distribution_set_item"]

        # ---------------------------------------------------------------------
        # Pass names back to global scope (s3.*)
        #
        return {"supply_distribution_set_id": distribution_set_id}

    # -------------------------------------------------------------------------
    def defaults(self):
        """ Safe defaults for names in case the module is disabled """

        return {"supply_distribution_set_id": FieldTemplate.dummy("distribution_set_id"),
                }

    # -------------------------------------------------------------------------
    @staticmethod
    def distribution_set_onvalidation(form):
        """
            Form validation of distribution sets:
            - title must be unique within organisation
        """

        T = current.T
        db = current.db
        s3db = current.s3db

        table = s3db.supply_distribution_set

        # Get form record ID
        record_id = get_form_record_id(form)

        # Get form record data
        data = get_form_record_data(form, table, ["name", "organisation_id"])
        name = data.get("name")
        organisation_id = data.get("organisation_id")

        if name:
            query = (table.name == name) & \
                    (table.organisation_id == organisation_id) & \
                    (table.deleted == False)
            if record_id:
                query = (table.id != record_id) & query
            row = db(query).select(table.id, limitby=(0, 1)).first()
            if row:
                form.errors["name"] = T('Distribution item set "%(name)s" already exists') % {"name": name}

    # -------------------------------------------------------------------------
    @staticmethod
    def distribution_set_item_onvalidation(form):
        """
            Form validation of distribution set items
            - items must appear only once per distribution set
            - standard quantity must be less than (or equal) maximum quantity
        """

        T = current.T
        db = current.db
        s3db = current.s3db

        table = s3db.supply_distribution_set_item

        # Get the form record ID
        record_id = get_form_record_id(form)

        # Get form/default data
        data = get_form_record_data(form, table, ["distribution_set_id",
                                                  "mode",
                                                  "item_id",
                                                  "quantity",
                                                  "quantity_max",
                                                  ])

        # Items may appear only once in the same distribution set
        distribution_set_id = data.get("distribution_set_id")
        if distribution_set_id:
            query = (table.distribution_set_id == distribution_set_id) & \
                    (table.item_id == data.get("item_id")) & \
                    (table.mode == data.get("mode")) & \
                    (table.deleted == False)
            if record_id:
                query = (table.id != record_id) & query
            row = db(query).select(table.id, limitby=(0, 1)).first()
            if row:
                form.errors.item_id = T("Item already registered for this set")

        # Make sure standard quantity is in range
        quantity = data.get("quantity")
        quantity_max = data.get("quantity_max")
        if quantity_max is not None and quantity > quantity_max:
            form.errors.quantity = T("Standard quantity must be less than or equal maximum quantity")

    # -------------------------------------------------------------------------
    @staticmethod
    def distribution_item_onaccept(form):
        """
            Onaccept of distribution item:
                - inherit person_id from distribution record
        """

        record_id = get_form_record_id(form)
        if not record_id:
            return

        db = current.db
        s3db = current.s3db

        dtable = s3db.supply_distribution
        itable = s3db.supply_distribution_item

        join = dtable.on(dtable.id == itable.distribution_id)
        row = db(itable.id == record_id).select(itable.id,
                                         dtable.person_id,
                                         join = join,
                                         limitby = (0, 1),
                                         ).first()
        if row:
            item = row.supply_distribution_item
            item.update_record(person_id = row.supply_distribution.person_id)

# =============================================================================
class supply_ItemRepresent(S3Represent):
    """ Representation of Supply Items """

    def __init__(self,
                 multiple = False,
                 show_link = False,
                 show_um = False,
                 translate = False,
                 truncate = None,
                 ):

        self.show_um = show_um
        if truncate is None:
            # Default: Truncate unless exporting in XLS format
            truncate = current.auth.permission.format not in ("xlsx", "xls")
        self.truncate = truncate

        # Need a custom lookup to join with Brand
        fields = ["supply_item.id",
                  "supply_item.name",
                  "supply_item.model",
                  "supply_brand.name",
                  ]
        if show_um:
            fields.append("supply_item.um")

        super().__init__(lookup = "supply_item",
                         fields = fields,
                         show_link = show_link,
                         translate = translate,
                         multiple = multiple,
                         )

    # -------------------------------------------------------------------------
    def lookup_rows(self, key, values, fields=None):
        """
            Custom lookup method for item rows, does a
            left join with the brand. Parameters
            key and fields are not used, but are kept for API
            compatibility reasons.

            Args:
                values: the supply_item IDs
        """

        db = current.db
        itable = current.s3db.supply_item
        btable = db.supply_brand

        left = btable.on(btable.id == itable.brand_id)

        qty = len(values)
        if qty == 1:
            query = (itable.id == values[0])
            limitby = (0, 1)
        else:
            query = (itable.id.belongs(values))
            limitby = (0, qty)

        rows = db(query).select(left = left,
                                limitby = limitby,
                                *self.fields)
        self.queries += 1
        return rows

    # -------------------------------------------------------------------------
    def represent_row(self, row):
        """
            Represent a single Row

            Args:
                row: the supply_item Row
        """

        name = row["supply_item.name"]
        model = row["supply_item.model"]
        brand = row["supply_brand.name"]

        fields = []
        if name:
            fields.append(name)
        if model:
            fields.append(model)
        if brand:
            fields.append(brand)
        name = " - ".join(fields)

        if self.show_um:
            um = row["supply_item.um"]
            if um:
                name = "%s (%s)" % (name, um)

        if self.truncate:
            name = s3_truncate(name)

        return s3_str(name)

# =============================================================================
class supply_ItemPackRepresent(S3Represent):
    """ Representation of Supply Item Packs """

    # -------------------------------------------------------------------------
    def lookup_rows(self, key, values, fields=None):
        """
            Custom lookup method for item_pack rows, does a left join with
            the item.

            Args:
                key: the primary key of the lookup table
                values: the supply_item_pack IDs
                fields: the fields to lookup (unused in this class,
                        retained for API compatibility)
        """

        db = current.db

        table = self.table
        itable = db.supply_item

        qty = len(values)
        if qty == 1:
            query = (key == values[0])
        else:
            query = (key.belongs(values))

        left = itable.on(table.item_id == itable.id)
        rows = db(query).select(table.id,
                                table.name,
                                table.quantity,
                                itable.um,
                                left = left,
                                limitby = (0, qty)
                                )
        self.queries += 1

        return rows

    # -------------------------------------------------------------------------
    def represent_row(self, row):
        """
            Represent a single Row

            Args:
                row: the Row (usually joined supply_item_pack/supply_item)
        """

        try:
            item = row.supply_item
            pack = row.supply_item_pack
        except AttributeError:
            # Missing join (external query?)
            item = {"um": "pc"}
            pack = row

        name = pack.get("name")
        if not name:
            return current.messages.UNKNOWN_OPT

        itable = current.s3db.supply_item
        um_represent = itable.um.represent

        quantity = pack.get("quantity")
        if quantity == 1 or quantity is None:
            return name
        else:
            quantity = int(quantity) if float.is_integer(quantity) else quantity
            # Include pack description (quantity x units of measurement)
            return "%s (%s %s)" % (name, quantity, um_represent(item.get("um")))

# =============================================================================
class supply_ItemCategoryRepresent(S3Represent):
    """ Representation of Supply Item Categories """

    def __init__(self,
                 translate = False,
                 show_link = False,
                 show_catalog = None,
                 use_code = True,
                 multiple = False,
                 ):

        if show_catalog is None:
            show_catalog = current.deployment_settings.get_supply_catalog_multi()
        self.show_catalog = show_catalog

        self.use_code = use_code

        # Need a custom lookup to join with Parent/Catalog
        fields = ["supply_item_category.id",
                  "supply_item_category.name",
                  "supply_item_category.code", # Always-included since used as fallback if no name
                  "supply_parent_item_category.name",
                  "supply_parent_item_category.code", # Always-included since used as fallback if no name
                  "supply_grandparent_item_category.name",
                  "supply_grandparent_item_category.code", # Always-included since used as fallback if no name
                  "supply_grandparent_item_category.parent_item_category_id",
                  ]
        if show_catalog:
            fields.append("supply_catalog.name")

        super().__init__(lookup = "supply_item_category",
                         fields = fields,
                         show_link = show_link,
                         translate = translate,
                         multiple = multiple,
                         )

    # -------------------------------------------------------------------------
    def lookup_rows(self, key, values, fields=None):
        """
            Custom lookup method for item category rows, does a
            left join with the parent category. Parameters
            key and fields are not used, but are kept for API
            compatibility reasons.

            Args:
                values: the supply_item_category IDs
        """

        db = current.db
        table = current.s3db.supply_item_category
        ptable = db.supply_item_category.with_alias("supply_parent_item_category")
        gtable = db.supply_item_category.with_alias("supply_grandparent_item_category")

        left = [ptable.on(ptable.id == table.parent_item_category_id),
                gtable.on(gtable.id == ptable.parent_item_category_id),
                ]
        if self.show_catalog:
            ctable = db.supply_catalog
            left.append(ctable.on(ctable.id == table.catalog_id))

        qty = len(values)
        if qty == 1:
            query = (table.id == values[0])
            limitby = (0, 1)
        else:
            query = (table.id.belongs(values))
            limitby = (0, qty)

        rows = db(query).select(left = left,
                                limitby = limitby,
                                *self.fields)
        self.queries += 1
        return rows

    # -------------------------------------------------------------------------
    def represent_row(self, row):
        """
            Represent a single Row

            Args:
                row: the supply_item_category Row
        """

        name = row["supply_item_category.name"]
        code = row["supply_item_category.code"]

        translate = self.translate
        if translate:
            T = current.T

        use_code = self.use_code
        if use_code:
            name = code
        elif not name:
            name = code
        elif translate:
            name = T(name)

        parent_name = row["supply_parent_item_category.name"]
        parent_code = row["supply_parent_item_category.code"]
        if parent_name or parent_code:
            if use_code:
                # Compact format
                sep = "-"
                parent = parent_code
            else:
                sep = " - "
                if not parent_name:
                    parent = parent_code
                else:
                    parent = parent_name
                    if translate:
                        parent = T(parent)
            name = "%s%s%s" % (name, sep, parent)
            grandparent_name = row["supply_grandparent_item_category.name"]
            grandparent_code = row["supply_grandparent_item_category.code"]
            if grandparent_name or grandparent_code:
                if use_code:
                    grandparent = grandparent_code
                else:
                    if not grandparent_name:
                        grandparent = grandparent_code
                    else:
                        grandparent = grandparent_name
                        if translate:
                            grandparent = T(grandparent)
                name = "%s%s%s" % (name, sep, grandparent)
                # Check for Great-grandparent
                # Trade-off "all in 1 row" vs "too many joins"
                greatgrandparent = row["supply_grandparent_item_category.parent_item_category_id"]
                if greatgrandparent:
                    # Assume no more than 6 levels of interest
                    db = current.db
                    table = current.s3db.supply_item_category
                    ptable = db.supply_item_category.with_alias("supply_parent_item_category")
                    gtable = db.supply_item_category.with_alias("supply_grandparent_item_category")
                    left = [ptable.on(ptable.id == table.parent_item_category_id),
                            gtable.on(gtable.id == ptable.parent_item_category_id),
                            ]
                    query = (table.id == greatgrandparent)
                    fields = [table.name,
                              table.code,
                              ptable.name,
                              ptable.code,
                              gtable.name,
                              gtable.code,
                              ]
                    row = db(query).select(*fields,
                                           left = left,
                                           limitby = (0, 1)
                                           ).first()
                    if row:
                        if use_code:
                            greatgrandparent = row["supply_item_category.code"]
                            greatgreatgrandparent = row["supply_parent_item_category.code"]
                        else:
                            greatgrandparent = row["supply_item_category.name"]
                            if greatgrandparent:
                                if translate:
                                    greatgrandparent = T(greatgrandparent)
                            else:
                                greatgrandparent = row["supply_item_category.code"]
                            greatgreatgrandparent = row["supply_parent_item_category.name"]
                            if greatgreatgrandparent:
                                if translate:
                                    greatgreatgrandparent = T(greatgreatgrandparent)
                            else:
                                greatgreatgrandparent = row["supply_parent_item_category.code"]
                        name = "%s%s%s" % (name, sep, greatgrandparent)
                        if greatgreatgrandparent:
                            name = "%s%s%s" % (name, sep, greatgreatgrandparent)
                            if use_code:
                                greatgreatgreatgrandparent = row["supply_grandparent_item_category.code"]
                            else:
                                greatgreatgreatgrandparent = row["supply_grandparent_item_category.name"]
                                if greatgreatgreatgrandparent:
                                    if translate:
                                        greatgreatgreatgrandparent = T(greatgreatgreatgrandparent)
                                else:
                                    greatgreatgreatgrandparent = row["supply_grandparent_item_category.code"]
                            if greatgreatgreatgrandparent:
                                name = "%s%s%s" % (name, sep, greatgreatgreatgrandparent)

        catalog = row.get("supply_catalog.name")
        if catalog:
            if translate:
                catalog = T(catalog)
            name = "%s > %s" % (catalog, name)

        return s3_str(name)

# =============================================================================
def item_um_from_name(name):
    """
        Retrieve the Unit of Measure from a name
    """

    for um_pattern in UM_PATTERNS:
        m = re.search(um_pattern, name)
        if m:
            um = m.group(1).strip()
            # Rename name from um
            name = re.sub(um_pattern, "", name)
            # Remove trailing , & wh sp
            name = re.sub("(,)$", "", name).strip()
            return (name, um)

    return (name, None)

# =============================================================================
def supply_catalog_rheader(r, tabs=None):
    """ Resource Header for Catalogs """

    if r.representation != "html":
        # Resource headers only used in interactive views
        return None

    tablename, record = s3_rheader_resource(r)
    if tablename != r.tablename:
        resource = current.s3db.resource(tablename, id=record.id)
    else:
        resource = r.resource

    rheader = None
    rheader_fields = []

    if record:

        T = current.T

        if not tabs:
            tabs = [(T("Edit Details"), None),
                    (T("Categories"), "item_category"),
                    (T("Catalog Items"), "catalog_item"),
                    ]

        rheader_fields = [["organisation_id"],
                          ["active"],
                          ]
        rheader_title = "name"

        # Generate rheader XML
        rheader = S3ResourceHeader(rheader_fields, tabs, title=rheader_title)
        rheader = rheader(r, table=resource.table, record=record)

    return rheader

# =============================================================================
def supply_item_rheader(r, tabs=None):
    """ Resource Header for Items """

    if r.representation != "html":
        # Resource headers only used in interactive views
        return None

    tablename, record = s3_rheader_resource(r)
    if tablename != r.tablename:
        resource = current.s3db.resource(tablename, id=record.id)
    else:
        resource = r.resource

    rheader = None
    rheader_fields = []

    if record:

        T = current.T
        settings = current.deployment_settings

        if not tabs:
            tabs = [(T("Edit Details"), None),
                    (T("Packs"), "item_pack"),
                    #(T("Alternative Items"), "item_alt"),
                    (T("In Inventories"), "inv_item"),
                    (T("Requested"), "req_item"),
                    (T("In Catalogs"), "catalog_item"),
                    #(T("Kit Items"), "kit_item")
                    ]
        if settings.get_supply_use_alt_name():
            tabs.insert(2, (T("Alternative Items"), "item_alt"))
        if settings.get_supply_kits() and record.kit:
            tabs.append((T("Kit Items"), "kit_item"))

        rheader_fields = [["catalog_id"],
                          ["item_category_id"],
                          ["code"],
                          ]
        rheader_title = "name"

        # Generate rheader XML
        rheader = S3ResourceHeader(rheader_fields, tabs, title=rheader_title)
        rheader = rheader(r, table=resource.table, record=record)

    return rheader

# =============================================================================
def supply_distribution_rheader(r, tabs=None):
    """ Distribution resource headers """

    if r.representation != "html":
        # Resource headers only used in interactive views
        return None

    tablename, record = s3_rheader_resource(r)
    if tablename != r.tablename:
        resource = current.s3db.resource(tablename, id=record.id)
    else:
        resource = r.resource

    rheader = None
    rheader_fields = []
    rheader_title = None

    if record:

        T = current.T

        if tablename == "supply_distribution_set":

            if not tabs:
                tabs = [(T("Basic Details"), None),
                        (T("Items"), "distribution_set_item"),
                        ]

            rheader_fields = [["organisation_id"],
                              ["active"],
                              ]
            rheader_title = "name"

        elif tablename == "supply_distribution":

            if not tabs:
                tabs = [(T("Basic Details"), None),
                        (T("Items"), "distribution_item"),
                        ]

            rheader_fields = [["organisation_id", "distribution_set_id"],
                              ["site_id"],
                              ["date"],
                              ]

        elif tablename == "supply_distribution_item":

            if not tabs:
                tabs = [(T("Item Details"), None),
                        ]

            # Show distribution details in header
            dist = resource.select(["distribution_id$person_id",
                                    "distribution_id$organisation_id",
                                    "distribution_id$site_id",
                                    "distribution_id$distribution_set_id",
                                    "distribution_id$date",
                                    "distribution_id$human_resource_id",
                                    ],
                                   represent = True,
                                   raw_data = True,
                                   ).rows
            if dist:
                dist = dist[0]
                #raw = dist._row

                beneficiary = lambda row: dist["supply_distribution.person_id"]
                organisation = lambda row: dist["supply_distribution.organisation_id"]
                site = lambda row: dist["supply_distribution.site_id"]
                staff = lambda row: dist["supply_distribution.human_resource_id"]
                date = lambda row: dist["supply_distribution.date"]

                rheader_fields = [[(T("Beneficiary"), beneficiary),
                                   (T("Organization"), organisation),
                                   ],
                                  [(T("Place"), site),
                                   (T("Staff Member in Charge"), staff),
                                   ],
                                  [(T("Date"), date),
                                   ],
                                  ]
            else:
                return None

        rheader = S3ResourceHeader(rheader_fields, tabs, title=rheader_title)
        rheader = rheader(r, table=resource.table, record=record)

    return rheader

# =============================================================================
class SupplyItemPackQuantity:
    """
        Field method for pack quantity of an item, used in req and inv
    """

    def __init__(self, tablename):
        self.tablename = tablename

    def __call__(self, row):

        default = 0

        tablename = self.tablename
        if hasattr(row, tablename):
            row = object.__getattribute__(row, tablename)
        try:
            item_pack_id = row.item_pack_id
        except AttributeError:
            return default

        if item_pack_id:
            return item_pack_id.quantity
        else:
            return default

# -----------------------------------------------------------------------------
def supply_item_pack_quantities(pack_ids):
    """
        Helper function to look up the pack quantities for
        multiple item_pack_ids in-bulk

        Args:
            pack_ids: iterable of item_pack_ids
    """

    table = current.s3db.supply_item_pack
    query = table.id.belongs(set(pack_ids))
    rows = current.db(query).select(table.id,
                                    table.quantity,
                                    )
    return dict((row.id, row.quantity) for row in rows)

# =============================================================================
def supply_item_entity_category(row):
    """ Virtual field: category """

    if hasattr(row, "supply_item_entity"):
        row = row.supply_item_entity
    else:
        return None
    try:
        item_id = row.item_id
    except AttributeError:
        return None

    table = current.s3db.supply_item
    query = (table.id == item_id)

    record = current.db(query).select(table.item_category_id,
                                      limitby=(0, 1)).first()
    if record:
        return table.item_category_id.represent(record.item_category_id)
    else:
        return current.messages["NONE"]

# -----------------------------------------------------------------------------
def supply_item_entity_country(row):
    """ Virtual field: country """

    if hasattr(row, "supply_item_entity"):
        row = row.supply_item_entity
    else:
        return None

    s3db = current.s3db
    etable = s3db.supply_item_entity

    ekey = etable._id.name

    try:
        instance_type = row.instance_type
    except AttributeError:
        return None
    try:
        entity_id = row[ekey]
    except AttributeError:
        return None

    itable = s3db[instance_type]
    ltable = s3db.gis_location

    if instance_type == "inv_inv_item":

        stable = s3db.org_site
        query = (itable[ekey] == entity_id) & \
                (stable.site_id == itable.site_id) & \
                (ltable.id == stable.location_id)
        record = current.db(query).select(ltable.L0,
                                          limitby=(0, 1)).first()

    elif instance_type == "inv_track_item":

        rtable = s3db.inv_recv
        stable = s3db.org_site
        query = (itable[ekey] == entity_id) & \
                (rtable.id == itable.recv_id) & \
                (stable.site_id == rtable.site_id) & \
                (ltable.id == stable.location_id)
        record = current.db(query).select(ltable.L0,
                                          limitby=(0, 1)).first()

    elif instance_type == "proc_plan_item":

        ptable = s3db.proc_plan
        stable = s3db.org_site
        query = (itable[ekey] == entity_id) & \
                (ptable.id == itable.plan_id) & \
                (stable.site_id == ptable.site_id) & \
                (ltable.id == stable.location_id)
        record = current.db(query).select(ltable.L0,
                                          limitby=(0, 1)).first()

    else:
        # @ToDo: Assets and req_items
        record = None

    if record:
        return record.L0 or current.T("Unknown")
    else:
        return current.messages["NONE"]

# -----------------------------------------------------------------------------
def supply_item_entity_organisation(row):
    """ Virtual field: organisation """

    if hasattr(row, "supply_item_entity"):
        row = row.supply_item_entity
    else:
        return None

    s3db = current.s3db
    etable = s3db.supply_item_entity

    ekey = etable._id.name

    try:
        instance_type = row.instance_type
    except AttributeError:
        return None
    try:
        entity_id = row[ekey]
    except AttributeError:
        return None

    organisation_represent = s3db.org_OrganisationRepresent(acronym=False)
    itable = s3db[instance_type]

    if instance_type == "inv_inv_item":

        stable = s3db.org_site
        query = (itable[ekey] == entity_id) & \
                (stable.site_id == itable.site_id)
        record = current.db(query).select(stable.organisation_id,
                                          limitby=(0, 1)).first()

    elif instance_type == "proc_plan_item":

        rtable = s3db.proc_plan
        stable = s3db.org_site
        query = (itable[ekey] == entity_id) & \
                (rtable.id == itable.plan_id) & \
                (stable.site_id == rtable.site_id)
        record = current.db(query).select(stable.organisation_id,
                                          limitby=(0, 1)).first()

    elif instance_type == "inv_track_item":

        rtable = s3db.inv_recv
        stable = s3db.org_site
        query = (itable[ekey] == entity_id) & \
                (rtable.id == itable.recv_id) & \
                (stable.site_id == rtable.site_id)
        record = current.db(query).select(stable.organisation_id,
                                          limitby=(0, 1)).first()

    else:
        # @ToDo: Assets and req_items
        record = None

    if record:
        return organisation_represent(record.organisation_id)
    else:
        return current.messages["NONE"]

# -----------------------------------------------------------------------------
def supply_item_entity_contacts(row):
    """ Virtual field: contacts (site_id) """

    if hasattr(row, "supply_item_entity"):
        row = row.supply_item_entity
    else:
        return None

    db = current.db
    s3db = current.s3db
    etable = s3db.supply_item_entity

    ekey = etable._id.name

    try:
        instance_type = row.instance_type
    except AttributeError:
        return None
    try:
        entity_id = row[ekey]
    except AttributeError:
        return None

    itable = s3db[instance_type]

    if instance_type == "inv_inv_item":

        query = (itable[ekey] == entity_id)
        record = db(query).select(itable.site_id,
                                  limitby=(0, 1)).first()

    elif instance_type == "inv_track_item":

        rtable = s3db.inv_recv
        query = (itable[ekey] == entity_id) & \
                (rtable.id == itable.recv_id)
        record = db(query).select(rtable.site_id,
                                  limitby=(0, 1)).first()

    elif instance_type == "proc_plan_item":

        ptable = s3db.proc_plan
        query = (itable[ekey] == entity_id) & \
                (ptable.id == itable.plan_id)
        record = db(query).select(ptable.site_id,
                                  limitby=(0, 1)).first()
    else:
        # @ToDo: Assets and req_items
        record = None

    default = current.messages["NONE"]

    if not record:
        return default

    otable = s3db.org_office
    query = (otable.site_id == record.site_id)
    office = db(query).select(otable.id,
                              otable.comments,
                              limitby=(0, 1)).first()

    if office:

        if current.request.extension in ("xlsx", "xls", "pdf"):
            if office.comments:
                return office.comments
            else:
                return default

        elif office.comments:
            comments = s3_comments_represent(office.comments,
                                             show_link=False)
        else:
            comments = default

        return A(comments,
                 _href = URL(f="office", args = [office.id]))

    else:
        return default


# -----------------------------------------------------------------------------
def supply_item_entity_status(row):
    """ Virtual field: status """

    if hasattr(row, "supply_item_entity"):
        row = row.supply_item_entity
    else:
        return None

    s3db = current.s3db
    etable = s3db.supply_item_entity

    ekey = etable._id.name

    try:
        instance_type = row.instance_type
    except AttributeError:
        return None
    try:
        entity_id = row[ekey]
    except AttributeError:
        return None

    itable = s3db[instance_type]

    status = None

    if instance_type == "inv_inv_item":

        query = (itable[ekey] == entity_id)
        record = current.db(query).select(itable.expiry_date,
                                          limitby=(0, 1)).first()
        if record:
            T = current.T
            if record.expiry_date:
                status = T("Stock Expires %(date)s") % {"date": record.expiry_date}
            else:
                status = T("In Stock")

    elif instance_type == "proc_plan_item":


        rtable = s3db.proc_plan
        query = (itable[ekey] == entity_id) & \
                (rtable.id == itable.plan_id)
        record = current.db(query).select(rtable.eta,
                                          limitby=(0, 1)).first()
        if record:
            T = current.T
            if record.eta:
                status = T("Planned %(date)s") % {"date": record.eta}
            else:
                status = T("Planned Procurement")

    elif instance_type == "inv_track_item":

        rtable = s3db.inv_recv
        query = (itable[ekey] == entity_id) & \
                (rtable.id == itable.send_inv_item_id)
        record = current.db(query).select(rtable.eta,
                                          limitby=(0, 1)).first()
        if record:
            T = current.T
            if record.eta:
                status = T("Order Due %(date)s") % {"date": record.eta}
            else:
                status = T("On Order")

    else:
        # @ToDo: Assets and req_items
        return current.messages["NONE"]

    return status or current.messages["NONE"]

# =============================================================================
def supply_item_autocomplete_filter(organisation_id, inactive=False):
    """
        Returns a filter query for supply_items by context organisation;
        for filtering of autocomplete-requests (search_ac)

        Args:
            organisation_id: the context organisation ID
            inactive: whether to include inactive catalogs

        Returns:
            Query
    """

    db = current.db
    s3db = current.s3db
    auth = current.auth

    # Sub-select for relevant catalogs
    ctable = s3db.supply_catalog
    query = auth.s3_accessible_query("read", ctable)
    if organisation_id:
        query &= (ctable.organisation_id == organisation_id) | \
                 (ctable.organisation_id == None)
    elif organisation_id == 0:
        query &= (ctable.organisation_id == None)
    if not inactive:
        query &= (ctable.active == True)
    query &= (ctable.deleted == False)
    catalogs = db(query)._select(ctable.id)

    # Sub-select for relevant entries
    ltable = s3db.supply_catalog_item
    query = (ltable.catalog_id.belongs(catalogs)) & \
            (ltable.deleted == False)
    entries = db(query)._select(ltable.item_id, distinct=True)

    itable = s3db.supply_item
    return itable.id.belongs(entries)

# -----------------------------------------------------------------------------
def supply_item_controller():
    """ RESTful CRUD controller """

    s3 = current.response.s3
    s3db = current.s3db

    def prep(r):

        if not r.component:

            resource = r.resource

            if r.method == "search_ac":

                get_vars = r.get_vars
                inactive = get_vars.get("inactive") == "1"
                obsolete = get_vars.get("obsolete") == "1"

                # Filter by context organisation
                org = get_vars.get("org")
                if org:
                    try:
                        organisation_id = int(org)
                    except (ValueError, TypeError):
                        r.error(400, "Invalid value for org-parameter")
                else:
                    organisation_id = None
                resource.add_filter(supply_item_autocomplete_filter(organisation_id,
                                                                    inactive = inactive,
                                                                    ))
                # Exclude items marked as obsolete
                if not obsolete:
                    resource.add_filter(FS("obsolete") == False)

            if r.get_vars.get("caller") in ("event_asset_item_id", "event_scenario_asset_item_id"):
                # Category is mandatory
                f = s3db.supply_item.item_category_id
                f.requires = f.requires.other
                # Need to tell Item Category controller that new categories must be 'Can be Assets'
                ADD_ITEM_CATEGORY = s3.crud_strings["supply_item_category"].label_create
                f.comment = PopupLink(c = "supply",
                                      f = "item_category",
                                      vars = {"assets": 1},
                                      label = ADD_ITEM_CATEGORY,
                                      title = current.T("Item Category"),
                                      tooltip = ADD_ITEM_CATEGORY,
                                      )

            if r.representation in ("xlsx", "xls"):
                # Use full Category names in XLS output
                s3db.supply_item.item_category_id.represent = \
                    supply_ItemCategoryRepresent(use_code=False)


        elif r.component_name == "inv_item":
            # Inventory Items need proper accountability so are edited through inv_adj
            s3db.configure("inv_inv_item",
                           listadd = False,
                           deletable = False,
                           )
            # Filter to just item packs for this Item
            s3db.inv_inv_item.item_pack_id.requires = IS_ONE_OF(current.db,
                                                                "supply_item_pack.id",
                                                                s3db.supply_item_pack_represent,
                                                                sort = True,
                                                                filterby = "item_id",
                                                                filter_opts = (r.record.id,),
                                                                )

        elif r.component_name == "req_item":
            # This is a report not a workflow
            s3db.configure("req_req_item",
                           listadd = False,
                           deletable = False,
                           )

        return True
    s3.prep = prep

    return current.crud_controller("supply", "item",
                                   rheader = supply_item_rheader,
                                   )

# =============================================================================
def supply_item_entity_controller():
    """
        RESTful CRUD controller
        - consolidated report of inv_item, recv_item & proc_plan_item
        @ToDo: Migrate JS to Static as part of migrating this to an
               S3Search Widget
    """

    T = current.T
    db = current.db
    s3db = current.s3db
    s3 = current.response.s3
    settings = current.deployment_settings

    tablename = "supply_item_entity"
    table = s3db[tablename]

    # CRUD strings
    s3.crud_strings[tablename] = Storage(
        label_create = T("Add Item"),
        title_display = T("Item Details"),
        title_list = T("Items"),
        title_update = T("Edit Item"),
        label_list_button = T("List Items"),
        label_delete_button = T("Delete Item"),
        msg_record_created = T("Item added"),
        msg_record_modified = T("Item updated"),
        msg_record_deleted = T("Item deleted"),
        msg_list_empty = T("No Items currently registered"))

    table.category = Field.Method("category",
                                  supply_item_entity_category)
    table.country = Field.Method("country",
                                 supply_item_entity_country)
    table.organisation = Field.Method("organisation",
                                      supply_item_entity_organisation)
    table.contacts = Field.Method("contacts",
                                  supply_item_entity_contacts)
    table.status = Field.Method("status",
                                supply_item_entity_status)

    # Allow VirtualFields to be sortable/searchable
    s3.no_sspag = True

    s3db.configure(tablename,
                   deletable = False,
                   insertable = False,
                   # @ToDo: Allow VirtualFields to be used to Group Reports
                   #report_groupby = "category",
                   list_fields = [(T("Category"), "category"),
                                  "item_id",
                                  "quantity",
                                  (T("Unit of Measure"), "item_pack_id"),
                                  (T("Status"), "status"),
                                  (current.messages.COUNTRY, "country"),
                                  (T("Organization"), "organisation"),
                                  #(T("Office"), "site"),
                                  (T("Contacts"), "contacts"),
                                 ],
                   extra_fields = ["instance_type"],
                  )

    def postp(r, output):
        if r.interactive and not r.record:
            # Provide some manual Filters above the list
            rheader = DIV()

            # Filter by Category
            table = s3db.supply_item_category
            etable = s3db.supply_item_entity
            itable = s3db.supply_item
            query = (etable.deleted == False) & \
                    (etable.item_id == itable.id) & \
                    (itable.item_category_id == table.id)
            categories = db(query).select(table.id,
                                          table.name,
                                          distinct=True)
            select = SELECT(_multiple="multiple", _id="category_dropdown")
            for category in categories:
                select.append(OPTION(category.name, _name=category.id))
            rheader.append(DIV(B("%s:" % T("Filter by Category")),
                               BR(),
                               select,
                               _class="rfilter"))

            # Filter by Status
            select = SELECT(_multiple="multiple", _id="status_dropdown")
            if settings.has_module("inv"):
                select.append(OPTION(T("In Stock")))
                select.append(OPTION(T("On Order")))
            if settings.has_module("proc"):
                select.append(OPTION(T("Planned Procurement")))
            rheader.append(DIV(B("%s:" % T("Filter by Status")),
                               BR(),
                               select,
                               _class="rfilter"))

            output["rheader"] = rheader

            # Find Offices with Items
            # @ToDo: Other Site types (how to do this as a big Join?)
            table = s3db.org_office
            otable = s3db.org_organisation
            ltable = s3db.gis_location
            fields = [ltable.L0,
                      #table.name,
                      otable.name]
            query = (table.deleted == False) & \
                    (table.organisation_id == otable.id) & \
                    (ltable.id == table.location_id)
            isites = []
            rsites = []
            psites = []
            # @ToDo: Assets & Req_Items
            # @ToDo: Try to do this as a Join?
            if settings.has_module("inv"):
                inv_itable = s3db.inv_inv_item
                iquery = query & (inv_itable.site_id == table.site_id)
                isites = db(iquery).select(distinct=True, *fields)
                inv_ttable = s3db.inv_track_item
                inv_rtable = s3db.inv_recv
                rquery = query & (inv_ttable.send_inv_item_id == inv_rtable.id) & \
                                 (inv_rtable.site_id == table.site_id)
                rsites = db(rquery).select(distinct=True, *fields)
            if settings.has_module("proc"):
                proc_ptable = s3db.proc_plan
                proc_itable = s3db.proc_plan_item
                pquery = query & (proc_itable.plan_id == proc_ptable.id) & \
                                 (proc_ptable.site_id == table.site_id)
                psites = db(pquery).select(distinct=True, *fields)
            sites = []
            for site in isites:
                if site not in sites:
                    sites.append(site)
            for site in rsites:
                if site not in sites:
                    sites.append(site)
            for site in psites:
                if site not in sites:
                    sites.append(site)

            # Filter by Country
            select = SELECT(_multiple="multiple", _id="country_dropdown")
            countries = []
            for site in sites:
                country = site.org_office.L0
                if country not in countries:
                    select.append(OPTION(country or T("Unknown")))
                    countries.append(country)
            rheader.append(DIV(B("%s:" % T("Filter by Country")),
                               BR(),
                               select,
                               _class="rfilter"))

            # Filter by Organisation
            select = SELECT(_multiple="multiple", _id="organisation_dropdown")
            orgs = []
            for site in sites:
                org = site.org_organisation.name
                if org not in orgs:
                    select.append(OPTION(org or T("Unknown")))
                    orgs.append(org)
            rheader.append(DIV(B("%s:" % T("Filter by Organization")),
                               BR(),
                               select,
                               _class="rfilter"))

            # http://datatables.net/api#fnFilter
            # Columns:
            #  1 = Category
            #  5 = Status (@ToDo: Assets & Req Items)
            #  6 = Country
            #  7 = Organisation
            # Clear column filter before applying new one
            #
            # @ToDo: Hide options which are no longer relevant because
            #        of the other filters applied
            #
            s3.jquery_ready.append('''
function filterColumns(){
 var oTable=$('#list').dataTable()
 var values=''
 $('#category_dropdown option:selected').each(function(){
  values+=$(this).text()+'|'
 })
 var regex=(values==''?'':'^'+values.slice(0, -1)+'$')
 oTable.fnFilter('',1,false)
 oTable.fnFilter(regex,1,true,false)
 values=''
 $('#status_dropdown option:selected').each(function(){
  if($(this).text()=="''' + T("On Order") + '''"){
   values+=$(this).text()+'|'+"''' + T("Order") + '''.*"+'|'
  }else if($(this).text()=="''' + T("Planned Procurement") + '''"){
   values+="''' + T("Planned") + '''.*"+'|'
  }else{
   values+=$(this).text()+'|'+"''' + T("Stock") + '''.*"+'|'
  }
 })
 var regex=(values==''?'':'^'+values.slice(0,-1)+'$')
 oTable.fnFilter('',5,false)
 oTable.fnFilter(regex,5,true,false)
 values=''
 $('#country_dropdown option:selected').each(function(){
  values+=$(this).text()+'|'
 })
 var regex=(values==''?'':'^'+values.slice(0,-1)+'$')
 oTable.fnFilter('',6,false)
 oTable.fnFilter(regex,6,true,false)
 values=''
 $('#organisation_dropdown option:selected').each(function(){
  values+=$(this).text()+'|'
 })
 var regex=(values==''? '':'^'+values.slice(0,-1)+'$')
 oTable.fnFilter('',7,false)
 oTable.fnFilter(regex,7,true,false)
}
$('#category_dropdown').change(function(){
 filterColumns()
 var values=[]
 $('#category_dropdown option:selected').each(function(){
  values.push($(this).attr('name'))
 })
 if(values.length){
  $('#list_formats a').attr('href',function(){
   var href=this.href.split('?')[0]+'?item_entity.item_id$item_category_id='+values[0]
   for(i=1;i<=(values.length-1);i++){
    href=href+','+values[i]
   }
   return href
   })
 }else{
  $('#list_formats a').attr('href',function(){
   return this.href.split('?')[0]
  })
 }
})
$('#status_dropdown').change(function(){
 filterColumns()
})
$('#country_dropdown').change(function(){
 filterColumns()
})
$('#organisation_dropdown').change(function(){
 filterColumns()
})''')

        return output
    s3.postp = postp

    return current.crud_controller("supply", "item_entity", hide_filter=True)

# -----------------------------------------------------------------------------
def supply_get_shipping_code(doctype, site_id, field):
    """
        Get a reference number for a shipping document

        Args:
            doctype: short name for the document type (e.g. WB, GRN)
            site_id: the sending/receiving site
            field: the field where the reference numbers are stored
                   (to look up the previous number for incrementing)
    """

    # Custom shipping code generator?
    custom_code = current.deployment_settings.get_supply_shipping_code()
    if callable(custom_code):
        return custom_code(doctype, site_id, field)

    db = current.db
    if site_id:
        table = current.s3db.org_site
        site = db(table.site_id == site_id).select(table.code,
                                                   limitby = (0, 1)
                                                   ).first()
        if site:
            scode = site.code
        else:
            scode = "###"
        code = "%s-%s-" % (doctype, scode)
    else:
        code = "%s-###-" % (doctype)
    number = 0
    if field:
        query = (field.like("%s%%" % code))
        ref_row = db(query).select(field,
                                   limitby = (0, 1),
                                   orderby = ~field
                                   ).first()
        if ref_row:
            ref = ref_row(field)
            number = int(ref[-6:])

    return "%s%06d" % (code, number + 1)

# END =========================================================================
