from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    idm_auto_stock = fields.Boolean(related='company_id.idm_auto_stock', readonly=False)
    idm_warehouse_id = fields.Many2one(related='company_id.idm_warehouse_id', readonly=False)
    idm_auto_validate = fields.Boolean(related='company_id.idm_auto_validate', readonly=False)
    idm_shortage_policy = fields.Selection(related='company_id.idm_shortage_policy', readonly=False)
    idm_process_refunds = fields.Boolean(related='company_id.idm_process_refunds', readonly=False)
    idm_reverse_on_reset = fields.Boolean(related='company_id.idm_reverse_on_reset', readonly=False)
    idm_skip_sale_lines = fields.Boolean(related='company_id.idm_skip_sale_lines', readonly=False)
