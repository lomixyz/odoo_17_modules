from odoo import models, fields, api, _
from odoo.exceptions import UserError

class AccountMove(models.Model):
    _inherit = 'account.move'

    delivery_count = fields.Integer(string="Deliveries", compute="_compute_delivery_count")

    def _compute_delivery_count(self):
        for move in self:
            move.delivery_count = self.env['stock.picking'].search_count([
                ('origin', '=', move.name),
                ('state', '!=', 'cancel')
            ])

    def action_view_delivery_orders(self):
        self.ensure_one()
        action = self.env.ref('stock.action_picking_tree_all').read()[0]
        action['domain'] = [('origin', '=', self.name)]
        action['context'] = {'default_origin': self.name}
        return action


    def action_post(self):
        """Ensure COGS is calculated for invoices, even if not linked to a sale order."""
        super(AccountMove, self).action_post()

        for invoice in self:
            if invoice.move_type == 'out_invoice':  # Only for customer invoices
                stock_moves = self.env['stock.move'].search([
                    ('origin', '=', invoice.name),
                    ('state', '=', 'done')
                ])

                if not stock_moves:
                    # ✅ No stock move exists → Create a stock move manually
                    self._create_stock_move(invoice)

                # ✅ Now trigger COGS journal entry
                self._generate_cogs_entry(invoice)

    def _create_stock_move(self, invoice):
        """Creates a stock move for products in the invoice to ensure COGS is triggered."""
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'outgoing'),
            ('warehouse_id', '!=', False)
        ], limit=1)

        if not picking_type:
            raise UserError(_("No delivery picking type found for the operation."))

        picking_vals = {
            'partner_id': invoice.partner_id.id,
            'picking_type_id': picking_type.id,
            'origin': invoice.name,
            'move_type': 'direct',
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': invoice.partner_id.property_stock_customer.id,
        }
        picking = self.env['stock.picking'].create(picking_vals)

        for line in invoice.invoice_line_ids:
            if line.product_id.type in ['consu', 'product']:
                move_vals = {
                    'name': line.name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'product_uom': line.product_uom_id.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                    'picking_id': picking.id,
                }
                move = self.env['stock.move'].create(move_vals)
                move._action_confirm()
                move._action_assign()
                move._action_done()

        picking.action_confirm()
        picking.action_assign()
        picking.button_validate()

    def _generate_cogs_entry(self, invoice):
        """Generates a COGS journal entry using the Anglo-Saxon accounting logic."""
        cogs_entries = self.env['stock.valuation.layer'].search([
            ('stock_move_id.origin', '=', invoice.name)
        ])

        if not cogs_entries:
            return  # No stock valuation available

        cogs_total = sum(cogs_entries.mapped('value'))
        if cogs_total <= 0:
            return

        cogs_account = self.env['account.account'].search([('code', '=', '500000')], limit=1)
        stock_account = self.env['account.account'].search([('code', '=', '140000')], limit=1)

        if not cogs_account or not stock_account:
            raise UserError(_("Please configure the COGS and Stock accounts."))

        move_vals = {
            'move_type': 'entry',
            'date': invoice.date,
            'ref': f"COGS for {invoice.name}",
            'journal_id': invoice.journal_id.id,
            'line_ids': [
                (0, 0, {
                    'account_id': cogs_account.id,
                    'name': "Cost of Goods Sold",
                    'debit': cogs_total,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': stock_account.id,
                    'name': "Inventory Stock Reduction",
                    'debit': 0.0,
                    'credit': cogs_total,
                }),
            ]
        }
        self.env['account.move'].create(move_vals).action_post()

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    available_qty = fields.Float(
        string="Available Qty",
        compute="_compute_available_qty",
        store=False
    )

    @api.depends('product_id')
    def _compute_available_qty(self):
        for line in self:
            if line.product_id:
                stock_quant = self.env['stock.quant'].search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id.usage', '=', 'internal')  # Consider only internal locations
                ])
                line.available_qty = sum(stock_quant.mapped('quantity'))
            else:
                line.available_qty = 0.0