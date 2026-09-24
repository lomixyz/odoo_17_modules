from odoo import Command, _, fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    invoice_id = fields.Many2one(
        'account.move',
        string='Source Invoice',
        readonly=True,
        copy=False,
        index='btree_not_null',
        ondelete='set null',
        help="The specific invoice that generated this transfer.",
    )
    idm_role = fields.Selection(
        [
            ('deduct', 'Invoice Delivery'),
            ('restock', 'Credit Note Return'),
            ('reversal', 'Invoice Reversal'),
        ],
        string='Invoice Operation',
        readonly=True,
        copy=False,
    )
    idm_reversed = fields.Boolean(
        string='Reversed',
        readonly=True,
        copy=False,
        help="The stock movement of this transfer was reversed after its invoice "
             "was reset to draft or cancelled.",
    )

    def _idm_effective(self):
        """Transfers that currently represent the invoice stock movement:
        not cancelled, not reversed and not a reversal themselves."""
        return self.filtered(
            lambda p: p.idm_role != 'reversal' and p.state != 'cancel' and not p.idm_reversed
        )

    # ------------------------------------------------------------------
    # Validation helper
    # ------------------------------------------------------------------
    def _idm_validate(self):
        """Validate without any pre-validation wizard (backorder, SMS...).
        Returns True when the transfer ends up done."""
        self.ensure_one()
        self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')).picked = True
        self.with_context(
            skip_backorder=True,
            picking_ids_not_to_backorder=self.ids,
            skip_sms=True,
            skip_expired=True,
        ).button_validate()
        return self.state == 'done'

    # ------------------------------------------------------------------
    # Reversal
    # ------------------------------------------------------------------
    def _idm_reverse(self):
        """Create and validate the exact opposite of this done transfer
        (same products, quantities and lots). Returns the reversal transfer."""
        self.ensure_one()
        done_moves = self.move_ids.filtered(lambda m: m.state == 'done' and m.quantity)
        if not done_moves:
            self.idm_reversed = True
            return self.browse()

        warehouse = self.picking_type_id.warehouse_id
        picking_type = self.picking_type_id.return_picking_type_id or (
            warehouse.in_type_id if self.picking_type_id.code == 'outgoing' else warehouse.out_type_id
        ) or self.picking_type_id

        reversal = self.create({
            'picking_type_id': picking_type.id,
            'partner_id': self.partner_id.id,
            'location_id': self.location_dest_id.id,
            'location_dest_id': self.location_id.id,
            'origin': _("Reversal of %s", self.name),
            'invoice_id': self.invoice_id.id,
            'idm_role': 'reversal',
            'return_id': self.id,
            'company_id': self.company_id.id,
            'move_type': 'direct',
            'move_ids': [Command.create({
                'name': move.name,
                'product_id': move.product_id.id,
                'product_uom_qty': move.quantity,
                'product_uom': move.product_uom.id,
                'location_id': move.location_dest_id.id,
                'location_dest_id': move.location_id.id,
                'origin_returned_move_id': move.id,
                'picking_type_id': picking_type.id,
                'company_id': self.company_id.id,
            }) for move in done_moves],
        })
        reversal.action_confirm()
        MoveLine = self.env['stock.move.line']
        for rmove in reversal.move_ids:
            rmove.move_line_ids.unlink()
            MoveLine.create([{
                'move_id': rmove.id,
                'picking_id': reversal.id,
                'product_id': ml.product_id.id,
                'product_uom_id': ml.product_uom_id.id,
                'quantity': ml.quantity,
                'lot_id': ml.lot_id.id,
                'location_id': ml.location_dest_id.id,
                'location_dest_id': ml.location_id.id,
                'picked': True,
                'company_id': self.company_id.id,
            } for ml in rmove.origin_returned_move_id.move_line_ids])
        reversal._idm_validate()
        self.idm_reversed = True
        return reversal

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_idm_open_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.invoice_id.id,
            'views': [(self.env.ref('account.view_move_form').id, 'form')],
        }
