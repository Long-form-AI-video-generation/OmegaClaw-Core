(= (sync-brand-atoms-to-api)
   (progn (py-call (atomspace_api.clear_brand_atoms))
          (collapse (match &self (Brand $sym $attr $val)
                           (py-call (atomspace_api.add_brand_atom $sym $attr $val))))))