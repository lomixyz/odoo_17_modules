def post_init_hook(env):
    """Link legacy transfers and protect historical invoices.

    1. Transfers created by older versions (linked only by ``origin`` name)
       are hard-linked to their invoice when the match is unique.
    2. Invoices already confirmed before installation without any linked
       transfer are flagged ``idm_update_stock = False`` so that a later
       reset/re-confirm never deducts stock for historical documents.
    """
    Picking = env['stock.picking'].sudo()
    Move = env['account.move'].sudo()

    orphans = Picking.search([
        ('invoice_id', '=', False),
        ('origin', '!=', False),
        ('picking_type_code', '=', 'outgoing'),
    ])
    if orphans:
        invoices = Move.search([
            ('move_type', '=', 'out_invoice'),
            ('state', '!=', 'draft'),
            ('name', 'in', list(set(orphans.mapped('origin')))),
        ])
        by_key = {}
        for invoice in invoices:
            key = (invoice.name, invoice.company_id.id)
            by_key[key] = invoice if key not in by_key else False  # ambiguous -> skip
        for picking in orphans:
            invoice = by_key.get((picking.origin, picking.company_id.id))
            if invoice:
                picking.write({'invoice_id': invoice.id, 'idm_role': 'deduct'})

    env.cr.execute("""
        UPDATE stock_picking SET idm_role = 'deduct'
         WHERE invoice_id IS NOT NULL AND idm_role IS NULL
    """)
    env.cr.execute("""
        UPDATE account_move am SET idm_update_stock = FALSE
         WHERE am.state != 'draft'
           AND am.idm_update_stock
           AND NOT EXISTS (SELECT 1 FROM stock_picking sp WHERE sp.invoice_id = am.id)
    """)
    env.invalidate_all()
    Picking.search([('invoice_id', '!=', False)]).invoice_id._compute_delivery_status()
