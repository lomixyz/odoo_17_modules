from collections import defaultdict

from odoo import api, fields, models
from odoo.tools import float_compare


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    available_qty = fields.Float(
        string="Available Qty",
        compute="_compute_available_qty",
        digits='Product Unit',
        store=True,
        help="Snapshot of the quantity on hand in the invoice warehouse, expressed in the "
             "line unit of measure. Recomputed while the invoice is a draft (as the product, "
             "quantity or warehouse change) and once more right when it is confirmed, then "
             "frozen - so each invoice keeps the figure it had at that time instead of "
             "showing today's stock level whenever it is reopened later.",
    )
    idm_qty_warning = fields.Boolean(
        string="Insufficient Stock",
        compute="_compute_available_qty",
        store=True,
    )
    idm_is_storable = fields.Boolean(
        string="Is Storable",
        compute="_compute_available_qty",
        store=True,
    )

    @api.depends('product_id', 'product_uom_id', 'quantity', 'move_id.state',
                 'move_id.idm_warehouse_id', 'move_id.company_id')
    def _compute_available_qty(self):
        storable = self.filtered(lambda l: l.product_id.is_storable)
        (self - storable).update({'available_qty': 0.0, 'idm_qty_warning': False, 'idm_is_storable': False})
        storable.idm_is_storable = True
        if not storable:
            return

        # Group the lines per warehouse / company to query stock.quant once per group
        groups = defaultdict(lambda: self.env['account.move.line'])
        for line in storable:
            move = line.move_id
            company = move.company_id or self.env.company
            warehouse = move.idm_warehouse_id or move._idm_default_warehouse(company)
            groups[(warehouse, company)] |= line

        Quant = self.env['stock.quant'].sudo()
        for (warehouse, company), lines in groups.items():
            domain = [
                ('product_id', 'in', lines.product_id.ids),
                ('location_id.usage', '=', 'internal'),
                ('company_id', '=', company.id),
            ]
            if warehouse:
                domain.append(('location_id', 'child_of', warehouse.view_location_id.id))
            on_hand = dict(Quant._read_group(domain, ['product_id'], ['quantity:sum']))
            for line in lines:
                product = line.product_id
                qty = on_hand.get(product, 0.0)
                if line.product_uom_id and line.product_uom_id != product.uom_id:
                    qty = product.uom_id._compute_quantity(qty, line.product_uom_id, round=False)
                line.available_qty = qty
                line.idm_qty_warning = (
                    line.move_id.move_type == 'out_invoice'
                    and line.move_id.state == 'draft'
                    and float_compare(line.quantity, qty, precision_digits=4) > 0
                )
