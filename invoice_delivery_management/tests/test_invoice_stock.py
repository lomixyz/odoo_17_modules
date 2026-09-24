from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestInvoiceStock(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.env.user.groups_id |= cls.env.ref('stock.group_stock_manager')
        cls.company = cls.company_data['company']
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.product = cls.env['product.product'].create({
            'name': 'IDM Storable', 'type': 'product', 'lst_price': 10.0,
        })
        cls.service = cls.env['product.product'].create({
            'name': 'IDM Service', 'type': 'service', 'lst_price': 5.0,
        })
        cls.env['stock.quant']._update_available_quantity(cls.product, cls.stock_location, 10.0)

    def _invoice(self, qty=3.0, move_type='out_invoice', product=None, uom=None, post=True):
        product = product or self.product
        move = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.partner_a.id,
            'invoice_date': '2026-01-01',
            'invoice_line_ids': [Command.create({
                'product_id': product.id,
                'quantity': qty,
                'price_unit': 10.0,
                **({'product_uom_id': uom.id} if uom else {}),
            })],
        })
        if post:
            move.action_post()
        return move

    def _on_hand(self):
        return self.product.with_context(warehouse_id=self.warehouse.id).qty_available

    # ------------------------------------------------------------------
    def test_01_confirm_deducts_stock(self):
        invoice = self._invoice(3.0)
        self.assertEqual(self._on_hand(), 7.0)
        self.assertEqual(invoice.delivery_count, 1)
        self.assertEqual(invoice.delivery_status, 'done')
        picking = invoice._get_linked_pickings()
        self.assertEqual(picking.state, 'done')
        self.assertEqual(picking.idm_role, 'deduct')
        self.assertEqual(picking.location_id, self.stock_location)

    def test_02_services_and_opt_out_ignored(self):
        self._invoice(2.0, product=self.service)
        invoice = self._invoice(3.0, post=False)
        invoice.idm_update_stock = False
        invoice.action_post()
        self.assertEqual(invoice.delivery_count, 0)
        self.assertEqual(self._on_hand(), 10.0)

    def test_03_uom_conversion(self):
        dozen = self.env.ref('uom.product_uom_dozen')
        self.env.user.groups_id |= self.env.ref('uom.group_uom')
        invoice = self._invoice(0.5, uom=dozen)  # 6 units
        self.assertEqual(self._on_hand(), 4.0)
        self.assertAlmostEqual(invoice.invoice_line_ids.available_qty, 4.0 / 12, places=2)

    def test_04_shortage_force(self):
        self.company.idm_shortage_policy = 'force'
        invoice = self._invoice(15.0)
        self.assertEqual(invoice.delivery_status, 'done')
        self.assertEqual(self._on_hand(), -5.0)

    def test_05_shortage_block(self):
        self.company.idm_shortage_policy = 'block'
        with self.assertRaises(UserError):
            self._invoice(15.0)

    def test_06_shortage_pending(self):
        self.company.idm_shortage_policy = 'pending'
        invoice = self._invoice(15.0)
        self.assertEqual(invoice.delivery_status, 'pending')
        self.assertEqual(self._on_hand(), 10.0)

    def test_07_no_auto_validate(self):
        self.company.idm_auto_validate = False
        invoice = self._invoice(3.0)
        self.assertEqual(invoice.delivery_status, 'pending')
        self.assertEqual(invoice._get_linked_pickings().state, 'assigned')

    def test_08_reset_reverses_and_repost(self):
        invoice = self._invoice(3.0)
        invoice.button_draft()
        self.assertEqual(self._on_hand(), 10.0)
        self.assertEqual(invoice.delivery_status, 'returned')
        invoice.invoice_line_ids.quantity = 4.0
        invoice.action_post()
        self.assertEqual(self._on_hand(), 6.0)
        self.assertEqual(invoice.delivery_status, 'done')
        self.assertEqual(invoice.delivery_count, 3)  # delivery, reversal, new delivery

    def test_09_cancel_reverses(self):
        invoice = self._invoice(3.0)
        invoice.button_cancel()
        self.assertEqual(invoice.state, 'cancel')
        self.assertEqual(self._on_hand(), 10.0)

    def test_10_reverse_disabled_keeps_link(self):
        self.company.idm_reverse_on_reset = False
        invoice = self._invoice(3.0)
        invoice.button_draft()
        invoice.action_post()
        self.assertEqual(self._on_hand(), 7.0)
        self.assertEqual(invoice.delivery_count, 1)

    def test_11_credit_note_restocks(self):
        invoice = self._invoice(3.0)
        refund = self._invoice(2.0, move_type='out_refund')
        self.assertEqual(self._on_hand(), 9.0)
        self.assertEqual(refund._get_linked_pickings().idm_role, 'restock')
        self.assertEqual(invoice.delivery_status, 'done')

    def test_12_credit_note_setting_off(self):
        self.company.idm_process_refunds = False
        refund = self._invoice(2.0, move_type='out_refund')
        self.assertFalse(refund.idm_update_stock)
        self.assertEqual(self._on_hand(), 10.0)

    def test_13_non_manager_blocked(self):
        user = self.env['res.users'].create({
            'name': 'IDM Billing', 'login': 'idm_billing',
            'groups_id': [Command.set([
                self.env.ref('account.group_account_invoice').id,
                self.env.ref('base.group_user').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        invoice = self._invoice(3.0)
        with self.assertRaises(UserError):
            invoice.with_user(user).button_draft()
        with self.assertRaises(UserError):
            invoice.with_user(user).button_cancel()
        # a billing user (no inventory rights) can still confirm invoices
        new_invoice = self._invoice(1.0, post=False).with_user(user)
        new_invoice.action_post()
        self.assertEqual(new_invoice.delivery_status, 'done')
        self.assertEqual(self._on_hand(), 6.0)

    def test_14_no_duplicate(self):
        invoice = self._invoice(3.0)
        invoice._idm_process_stock()
        self.assertEqual(invoice.delivery_count, 1)
        self.assertEqual(self._on_hand(), 7.0)

    def test_15_available_qty_warning(self):
        invoice = self._invoice(12.0, post=False)
        line = invoice.invoice_line_ids
        self.assertEqual(line.available_qty, 10.0)
        self.assertTrue(line.idm_qty_warning)

    def test_16_form_view(self):
        with Form(self.env['account.move'].with_context(default_move_type='out_invoice')) as move_form:
            move_form.partner_id = self.partner_a
            move_form.invoice_date = '2026-01-01'
            with move_form.invoice_line_ids.new() as line:
                line.product_id = self.product
                line.quantity = 2.0
        invoice = move_form.save()
        self.assertTrue(invoice.idm_update_stock)
        self.assertEqual(invoice.idm_warehouse_id, self.warehouse)
        invoice.action_post()
        self.assertEqual(self._on_hand(), 8.0)

    def test_17_delete_draft_cleans_pending(self):
        self.company.idm_auto_validate = False
        invoice = self._invoice(3.0)
        picking = invoice._get_linked_pickings()
        invoice.button_draft()
        self.assertEqual(picking.state, 'cancel')
        invoice.unlink()
        self.assertFalse(picking.exists())

    def test_18_lot_tracked_product(self):
        self.env.user.groups_id |= self.env.ref('stock.group_production_lot')
        product = self.env['product.product'].create({
            'name': 'IDM Lot', 'type': 'product', 'tracking': 'lot',
        })
        lot = self.env['stock.lot'].create({
            'name': 'LOT-IDM', 'product_id': product.id, 'company_id': self.company.id,
        })
        self.env['stock.quant']._update_available_quantity(product, self.stock_location, 5.0, lot_id=lot)
        invoice = self._invoice(2.0, product=product)
        self.assertEqual(invoice.delivery_status, 'done')
        self.assertEqual(invoice._get_linked_pickings().move_line_ids.lot_id, lot)
        self.assertEqual(lot.product_qty, 3.0)
        invoice.button_draft()
        lot.invalidate_recordset()
        self.assertEqual(lot.product_qty, 5.0)
        # shortage on a tracked product can't be forced: the transfer waits
        invoice.invoice_line_ids.quantity = 8.0
        invoice.action_post()
        self.assertEqual(invoice.delivery_status, 'pending')

    def test_19_legacy_link_hook(self):
        from odoo.addons.invoice_delivery_management.hooks import post_init_hook
        invoice = self._invoice(1.0, product=self.service)
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'origin': invoice.name,
        })
        post_init_hook(self.env)
        self.assertEqual(picking.invoice_id, invoice)
        self.assertEqual(picking.idm_role, 'deduct')
        self.assertEqual(invoice.delivery_count, 1)
