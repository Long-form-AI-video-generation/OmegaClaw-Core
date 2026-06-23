; -- Per-agent skill grants:  (SkillGrant <instance-id> <skill-name>) ---------
; CoSA — operator's single point of contact & orchestrator.
!(add-atom &self (SkillGrant cosa check-my-tasks))
!(add-atom &self (SkillGrant cosa complete-task))
!(add-atom &self (SkillGrant cosa post-task))
!(add-atom &self (SkillGrant cosa send))
; CDA — creative director. Returns concepts/briefs to CoSA via complete-task
!(add-atom &self (SkillGrant cda check-my-tasks))
!(add-atom &self (SkillGrant cda complete-task))
!(add-atom &self (SkillGrant cda campaign-ideas))
; SWA — scriptwriter. Owns script generation; returns results via complete-task.
!(add-atom &self (SkillGrant swa check-my-tasks))
!(add-atom &self (SkillGrant swa complete-task))
!(add-atom &self (SkillGrant swa generate-script))

; getSkills: show this instance only the skills it has been granted. An
; instance with no grants at all (ungoverned, e.g. `default`) gets the full
(= (getSkills)
   (let $docs (collapse (match &self (SkillDoc $name $desc)
                               (if (skillAllowed $name) $desc (empty))))
        (if (== $docs ())
            ""
            (progn (translatePredicate (atomic_list_concat $docs "\n" $joined))
                   (translatePredicate (atom_string $joined $js))
                   $js))))

; skillAllowed: True iff $name is callable by the current instance. Ungoverned
; instances (no grants) allow everything, matching getSkills' fallback.
(= (skillAllowed $name)
   (let $inst (sread (py-call (agentverse.get_instance_id)))
        (if (== () (collapse (match &self (SkillGrant $inst $g) True)))
            True
            (if (== () (collapse (match &self (SkillGrant $inst $name) True)))
                False
                True))))


(= (read-file $file)
   (progn (translatePredicate (exists_file $file))
          (translatePredicate (read_file_to_string $file $content ()))
          $content))

(= (write-file $file $str)
   (progn (translatePredicate (open $file write $Out))
          (translatePredicate (write $Out $str))
          (translatePredicate (close $Out))
          WRITE-FILE-SUCCESS))

(= (append-file $file $str)
   (progn (translatePredicate (exists_file $file))
          (translatePredicate (open $file append $Out))
          (translatePredicate (write $Out $str))
          (translatePredicate (nl $Out)),
          (translatePredicate (close $Out))
          APPEND-FILE-SUCCESS))

(= (tavily-search $query)
   (py-call (agentverse.tavily_search $query)))

(= (technical-analysis $ticker)
   (py-call (agentverse.technical_analysis $ticker)))

; -- Brand identity ------------------------------------------------

(= (find-brand-in-brief $brand_name)
   (let $sym (sread (py-call (agentverse._brand_sym $brand_name)))
        (let $exists (collapse (match &self (Brand $sym name $_) True))
             (if (== $exists ())
                 ""
                 $sym))))

(= (get-brand-context $brand)
   (let $kvs (collapse (match &self (Brand $brand $attr $val)
                               (progn (translatePredicate (atom_string $attr $astr))
                                      (string_concat $astr (string_concat ": " $val)))))
        (if (== $kvs ())
            ""
            (progn (translatePredicate (atomic_list_concat $kvs "\n" $ja))
                   (translatePredicate (atom_string $ja $js))
                   $js))))

(= (campaign-ideas $brief)
   (let $check (py-call (agentverse.check_brand_existance $brief))
        (let $brand_name (py-call (agentverse.extract_brand_from_check $check))
             (let $brand (find-brand-in-brief $brand_name)
                  (let $bctx (get-brand-context $brand)
                       (let $payload (py-call (agentverse.build_campaign_brief $brand $check $bctx))
                            (let $result (py-call (agentverse.campaign_ideas $payload))
                                 (let $atoms_expr (py-call (agentverse.store_campaign_ideas $result))
                                      (let $menu (py-call (agentverse.format_ideas_menu $result))
                                           (let $_ (py-call (agentverse.auto_complete_task_for_brief $brief $menu))
                                                (progn (metta $atoms_expr)
                                                       (send $menu)
                                                       "CAMPAIGN-IDEAS-DONE: concepts generated, stored, and the originating task closed. Do NOT call campaign-ideas again for this brief — call check-my-tasks for any new task, otherwise stop.")))))))))))

(= (generate-script $brief)
   (if (skillAllowed generate-script)
       (let $parsed (py-call (agentverse.parse_script_request $brief))
            (let $brand_name (py-call (agentverse.extract_field_from_json $parsed brand))
                 (let $campaign (py-call (agentverse.extract_field_from_json $parsed campaign))
                      (let $idea (py-call (agentverse.extract_field_from_json $parsed idea))
                           (let $brand (find-brand-in-brief $brand_name)
                                (let $bctx (get-brand-context $brand)
                                     (let $payload (py-call (agentverse.build_script_brief $brand_name $campaign $idea $bctx))
                                          (let $result (py-call (agentverse.generate_script $payload))
                                               (let $_ (py-call (agentverse.store_generated_script $brand_name $campaign $idea $result))
                                                    (let $_ (py-call (agentverse.auto_complete_task_for_brief $brief $result))
                                                         (progn (send $result)
                                                                $result)))))))))))
       "PERMISSION-DENIED: generate-script is not granted to this agent — route script generation through the agent that owns it"))

;-- Interagent task routing -------------------------------------------------
     (= (post-task $to $message)
          (if (skillAllowed post-task)
              (py-call (agentverse.post_task_summary $to $message))
              "PERMISSION-DENIED: post-task is not granted to this agent — return your work to CoSA via complete-task instead"))
     (= (check-my-tasks)
          (let $summary (py-call (agentverse.get_pending_tasks_as_metta (instanceId)))
               (if (== $summary "NO-TASKS")
                    "NO-TASKS"
                    (py-call (helper.normalize_string $summary)))))

     (= (complete-task $id $result)
          (py-call (agentverse.complete_task_summary $id $result)))

!(import_prolog_functions_from_file (library OmegaClaw-Core ./src/skills.pl) (shell first_char gc read_file_tail))

(= (metta $str)
   (let $code (sread $str)
        (repr (swrite (eval $code)))))

(= (pin $x)
   PIN-SUCCESS)
