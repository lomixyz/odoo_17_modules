from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    idm_auto_stock = fields.Boolean(
        string='Update Stock from Invoices',
        default=True,
        help="Deduct the invoiced products from stock when a customer invoice is confirmed.",
    )
    idm_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Invoice Warehouse',
        help="Default warehouse used for invoice stock moves. "
             "If empty, the user's default warehouse or the first warehouse of the company is used.",
    )
    idm_auto_validate = fields.Boolean(
        string='Validate Deliveries Automatically',
        default=True,
        help="Validate the delivery immediately so stock is deducted at invoice confirmation. "
             "If disabled, the delivery is created and reserved, waiting for the warehouse team.",
    )
    idm_shortage_policy = fields.Selection(
        [
            ('force', 'Allow negative stock'),
            ('pending', 'Keep the delivery waiting'),
            ('block', 'Block invoice confirmation'),
        ],
        string='When Stock is Insufficient',
        default='force',
        required=True,
    )
    idm_process_refunds = fields.Boolean(
        string='Return Stock on Credit Notes',
        default=True,
        help="Confirming a customer credit note returns its products to stock.",
    )
    idm_reverse_on_reset = fields.Boolean(
        string='Reverse Stock on Reset / Cancel',
        default=True,
        help="Resetting to draft or cancelling an invoice reverses its stock movement. "
             "Re-confirming the invoice creates a fresh movement with the new quantities.",
    )
    idm_skip_sale_lines = fields.Boolean(
        string='Skip Lines from Sales Orders',
        default=True,
        help="Invoice lines linked to a Sales Order are delivered by the Sales Order itself "
             "and are ignored to avoid a double deduction.",
    )
