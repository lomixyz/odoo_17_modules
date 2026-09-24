from collections import defaultdict

from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

STOCK_MOVE_TYPES = ('out_invoice', 'out_refund')

DELIVERY_STATUS = [
    ('none', 'Not Linked'),
    ('pending', 'Waiting'),
    ('partial', 'Partially Done'),
    ('done', 'Done'),
    ('returned', 'Reversed'),
]


class AccountMove(models.Model):
    _inherit = 'account.move'

    idm_picking_ids = fields.One2many(
        'stock.picking', 'invoice_id',
        string='Stock Transfers',
        copy=False,
        groups='stock.group_stock_user',
    )
    delivery_count = fields.Integer(
        string='Delivery',
        compute='_compute_delivery_count',
        compute_sudo=True,
    )
    delivery_status = fields.Selection(
        DELIVERY_STATUS,
        string='Delivery Status',
        compute='_compute_delivery_status',
        compute_sudo=True,
        store=True,
        copy=False,
    )
    idm_update_stock = fields.Boolean(
        string='Update Stock',
        compute='_compute_idm_update_stock',
        store=True,
        readonly=False,
        copy=False,
        help="Deduct (invoice) or return (credit note) the products in stock when this document is confirmed.",
    )
    idm_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        compute='_compute_idm_warehouse_id',
        store=True,
        readonly=False,
        copy=False,
        check_company=True,
        help="Warehouse the products are delivered from (or returned to).",
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    def _get_linked_pickings(self):
        """Return all transfers linked to this invoice (hard link by database id)."""
        self.ensure_one()
        return self.env['stock.picking'].sudo().search([('invoice_id', '=', self.id)])

    def _compute_delivery_count(self):
        data = dict(self.env['stock.picking'].sudo()._read_group(
            [('invoice_id', 'in', self.ids)], ['invoice_id'], ['__count'],
        )) if self.ids else {}
        for record in self:
            record.delivery_count = data.get(record, 0)

    @api.depends('idm_picking_ids.state', 'idm_picking_ids.idm_reversed')
    def _compute_delivery_status(self):
        for record in self:
            pickings = record.idm_picking_ids
            effective = pickings._idm_effective()
            if not effective:
                reversed_any = any(p.idm_reversed for p in pickings)
                record.delivery_status = 'returned' if reversed_any else 'none'
            elif all(p.state == 'done' for p in effective):
                record.delivery_status = 'done'
            elif any(p.state == 'done' for p in effective):
                record.delivery_status = 'partial'
            else:
                record.delivery_status = 'pending'

    @api.depends('move_type', 'company_id')
    def _compute_idm_update_stock(self):
        for record in self:
            company = record.company_id or self.env.company
            if not company.idm_auto_stock or record.move_type not in STOCK_MOVE_TYPES:
                record.idm_update_stock = False
            elif record.move_type == 'out_refund':
                record.idm_update_stock = company.idm_process_refunds
            else:
                record.idm_update_stock = True

    @api.depends('company_id', 'move_type')
    def _compute_idm_warehouse_id(self):
        cache = {}
        for record in self:
            if record.move_type not in STOCK_MOVE_TYPES:
                record.idm_warehouse_id = False
                continue
            company = record.company_id or self.env.company
            if company not in cache:
                cache[company] = self._idm_default_warehouse(company)
            record.idm_warehouse_id = cache[company]

    @api.model
    def _idm_default_warehouse(self, company):
        warehouse = company.sudo().idm_warehouse_id
        if not warehouse:
            warehouse = self.env.user.with_company(company)._get_default_warehouse_id()
            if warehouse.company_id != company:
                warehouse = self.env['stock.warehouse'].sudo().search(
                    [('company_id', '=', company.id)], limit=1)
        return warehouse

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _has_done_delivery(self):
        """Return True if an active (not reversed) linked transfer is done."""
        self.ensure_one()
        return any(p.state == 'done' for p in self._get_linked_pickings()._idm_effective())

    def _idm_check_manager(self, message):
        """Block non-managers on invoices having a completed delivery."""
        if self.env.user.has_group('account.group_account_manager'):
            return
        for move in self:
            if move.move_type in STOCK_MOVE_TYPES and move._has_done_delivery():
                raise UserError(message % move.display_name)

    def _idm_log(self, body):
        """Log on the chatter as the current user (sudo: never fails on a missing sender email)."""
        self.ensure_one()
        self.sudo().message_post(body=body, subtype_xmlid='mail.mt_note')

    def _idm_prepare_stock_lines(self):
        """Aggregate the storable/consumable invoice lines per product,
        converted to the product unit of measure."""
        self.ensure_one()
        skip_sale = self.company_id.idm_skip_sale_lines
        quantities = defaultdict(float)
        descriptions = defaultdict(list)
        for line in self.invoice_line_ids:
            product = line.product_id
            if line.display_type != 'product' or not product or product.type not in ('product', 'consu'):
                continue
            if skip_sale and 'sale_line_ids' in line._fields and line.sale_line_ids:
                continue
            qty = line.quantity
            if line.product_uom_id and line.product_uom_id != product.uom_id:
                qty = line.product_uom_id._compute_quantity(qty, product.uom_id)
            quantities[product] += qty
            if line.name:
                descriptions[product].append(line.name)
        return [
            (product, qty, '; '.join(descriptions[product]) or product.display_name)
            for product, qty in quantities.items()
            if float_compare(qty, 0.0, precision_rounding=product.uom_id.rounding) > 0
        ]

    def _idm_create_picking(self, lines):
        self.ensure_one()
        company = self.company_id
        warehouse = self.idm_warehouse_id or self._idm_default_warehouse(company)
        if not warehouse:
            raise UserError(_("No warehouse found for company %s. Please configure one "
                              "in Invoicing settings.", company.display_name))
        partner = self.partner_shipping_id or self.partner_id
        customer_location = (partner.with_company(company).property_stock_customer
                             or self.env.ref('stock.stock_location_customers'))
        if self.move_type == 'out_invoice':
            role = 'deduct'
            picking_type = warehouse.out_type_id
            src = picking_type.default_location_src_id or warehouse.lot_stock_id
            dest = customer_location
        else:
            role = 'restock'
            picking_type = warehouse.out_type_id.return_picking_type_id or warehouse.in_type_id
            src = customer_location
            dest = picking_type.default_location_dest_id or warehouse.lot_stock_id
        if not picking_type:
            raise UserError(_("No delivery operation type found for warehouse %s.", warehouse.display_name))

        return self.env['stock.picking'].sudo().with_company(company).create({
            'partner_id': partner.id,
            'picking_type_id': picking_type.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'origin': self.name,
            'invoice_id': self.id,
            'idm_role': role,
            'move_type': 'direct',
            'company_id': company.id,
            'move_ids': [Command.create({
                'name': description,
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
                'location_id': src.id,
                'location_dest_id': dest.id,
                'picking_type_id': picking_type.id,
                'company_id': company.id,
            }) for product, qty, description in lines],
        })

    def _idm_process_picking(self, picking):
        """Reserve then validate the transfer according to the company policy."""
        self.ensure_one()
        company = self.company_id
        picking.action_confirm()
        picking.action_assign()

        if not company.idm_auto_validate:
            self._idm_log(_("Stock transfer %s created and waiting for validation.",
                                     picking._get_html_link()))
            return

        shortage = picking.move_ids.filtered(
            lambda m: m.product_id.type == 'product' and float_compare(
                m.quantity, m.product_uom_qty, precision_rounding=m.product_uom.rounding) < 0
        )
        if shortage and picking.picking_type_id.code == 'outgoing':
            policy = company.idm_shortage_policy
            if policy == 'block':
                details = '\n'.join(
                    '- %s: %s %s / %s %s' % (
                        m.product_id.display_name, m.product_uom_qty, m.product_uom.name,
                        m.quantity, _('available'))
                    for m in shortage)
                raise UserError(_("Not enough stock to confirm %(invoice)s:\n%(details)s",
                                  invoice=self.display_name, details=details))
            if policy == 'pending' or shortage.filtered(lambda m: m.has_tracking != 'none'):
                self._idm_log(_("Not enough stock: transfer %s is waiting for availability.",
                                         picking._get_html_link()))
                return
            for move in shortage:
                move.quantity = move.product_uom_qty

        missing_lots = picking.move_line_ids.filtered(
            lambda ml: ml.product_id.tracking != 'none' and not ml.lot_id and not ml.lot_name)
        if missing_lots:
            self._idm_log(_("Transfer %s needs Lot/Serial numbers and is waiting for validation.",
                                     picking._get_html_link()))
            return

        if picking._idm_validate():
            self._idm_log(_("Stock updated by transfer %s.", picking._get_html_link()))
        else:
            self._idm_log(_("Transfer %s is waiting for validation.", picking._get_html_link()))

    def _idm_process_stock(self):
        for move in self:
            company = move.company_id
            if (move.state != 'posted' or move.move_type not in STOCK_MOVE_TYPES
                    or not move.idm_update_stock or not company.idm_auto_stock):
                continue
            # Avoid duplicates: an active transfer already represents this invoice
            if move._get_linked_pickings()._idm_effective():
                continue
            lines = move._idm_prepare_stock_lines()
            if not lines:
                continue
            picking = move._idm_create_picking(lines)
            move._idm_process_picking(picking)

    def _idm_reverse_stock(self):
        for move in self:
            if move.move_type not in STOCK_MOVE_TYPES or not move.company_id.idm_reverse_on_reset:
                continue
            reversed_names = []
            for picking in move._get_linked_pickings()._idm_effective():
                if picking.state == 'done':
                    reversal = picking._idm_reverse()
                    if reversal:
                        reversed_names.append(reversal._get_html_link())
                else:
                    picking.action_cancel()
            if reversed_names:
                move._idm_log(_("Stock movement reversed by %s.",
                                         Markup(', ').join(reversed_names)))

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------
    def unlink(self):
        self._idm_check_manager(_(
            "You cannot delete \"%s\" because it has a completed delivery.\n"
            "Only an Accounting Manager can delete such invoices."))
        for move in self.filtered(lambda m: m.move_type in STOCK_MOVE_TYPES):
            # Cancel then delete the pending transfers so they are never
            # reused by a future invoice that gets the same name
            pickings = move._get_linked_pickings()
            pickings.filtered(lambda p: p.state not in ('done', 'cancel')).action_cancel()
            pickings.filtered(lambda p: p.state == 'cancel').unlink()
        return super().unlink()

    def button_draft(self):
        self._idm_check_manager(_(
            "You cannot reset \"%s\" to draft because it has a completed delivery.\n"
            "Only an Accounting Manager can do this."))
        res = super().button_draft()
        self._idm_reverse_stock()
        return res

    def button_cancel(self):
        self._idm_check_manager(_(
            "You cannot cancel \"%s\" because it has a completed delivery.\n"
            "Only an Accounting Manager can cancel such invoices."))
        res = super().button_cancel()
        self._idm_reverse_stock()
        return res

    def action_post(self):
        res = super().action_post()
        self._idm_process_stock()
        return res

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_view_delivery_orders(self):
        self.ensure_one()
        pickings = self._get_linked_pickings()
        action = self.env['ir.actions.act_window']._for_xml_id('stock.action_picking_tree_all')
        action['domain'] = [('id', 'in', pickings.ids)]
        action['context'] = {'default_invoice_id': self.id, 'default_origin': self.name, 'create': False}
        if len(pickings) == 1:
            action['views'] = [(self.env.ref('stock.view_picking_form').id, 'form')]
            action['res_id'] = pickings.id
        return action
