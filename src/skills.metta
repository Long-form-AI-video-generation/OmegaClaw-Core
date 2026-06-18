(= (getSkills)
   (;INTERNAL:
    "- Remember a particular string such as skills and memories: remember string"
    "- Query long-term embedding memory for skills and memories with short phrases only: query string"
    "- Episodes searches history for episodes around a time stamp, time format is same as in TIME: episodes time_string"
    "- Pin a certain string as short-term working memory item to keep track of task state: pin string"
    ;SHELL AND FILE I/O:
    "- Execute shell command without apostrophe in string, it returns the command output to you: shell string"
    "- Read file to string: read-file filename"
    "- Write string to file: write-file filename string"
    "- Append line to file: append-file filename string",
    ;COMMUNICATION CHANNELS:
    "- Send message to user: send string"
    "- Search the web: search string"
    "- Search the web using the Tavily Search Agent: tavily-search string"
    "- Get technical analysis for a stock ticker using the Technical Analysis Agent: technical-analysis ticker"
    ;BRAND IDENTITY:
    "- Generate campaign ideas for a brand: campaign-ideas string"
    "- Generate a script for a user-approved campaign idea: generate-script brand | campaign-title | idea-name"

    ;TASK EXECUTION:
    "- Post a task to another agent: post-task agent-id message"
    "- Check your own pending tasks: check-my-tasks"
    "- Mark a task as done: complete-task task-id result"

    ;CODE EXECUTION:
    "- Execute MeTTa expression: metta sexpression"
    "Example to invoke Non-Axiomatic Logic via MeTTa: "
    "metta (|- ((--> (× sam garfield) friend) (stv 1.0 0.9))"
    "          ((--> garfield animal) (stv 1.0 0.9)))"
    "metta (|- ((==> (--> (× $1 elephant) eat) (--> $1 ([] dangerous))) (stv 1.0 0.9))"
    "          ((--> (× tiger elephant) eat) (stv 1.0 0.9)))"
    "Also: note the $1 for independent variables, and for negated knowledge use (stv 0.0 0.9)"
    "Additionally |- also works for revision, to merge evidence even when the term of both premises is the same."
    "You can also use PLN:"
    "metta (|~ ((Implication (Inheritance $1 (IntSet Feathered))"
    "           (Inheritance $1 Bird)) (stv 1.0 0.9))"
    "          ((Inheritance Pingu (IntSet Feathered)) (stv 1.0 0.9)))"))


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
   (let $sym (sread $brand_name)
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
                                                       $menu)))))))))))

(= (generate-script $brief)
   (let $parsed (py-call (agentverse.parse_script_request $brief))
        (let $brand_name (py-call (agentverse.extract_field_from_json $parsed brand))
             (let $campaign (py-call (agentverse.extract_field_from_json $parsed campaign))
                  (let $idea (py-call (agentverse.extract_field_from_json $parsed idea))
                       (let $brand (find-brand-in-brief $brand_name)
                            (let $bctx (get-brand-context $brand)
                                 (let $payload (py-call (agentverse.build_script_brief $brand_name $campaign $idea $bctx))
                                      (let $result (py-call (agentverse.generate_script $payload))
                                           (progn (send $result)
                                                  $result))))))))))                                                 

;-- Interagent task routing -------------------------------------------------
     (= (post-task $to $message)
          (py-call (agentverse.post_task_summary $to $message)))

     ; check-my-tasks: CDA auto-advances — it fetches the oldest pending brief
     ; and runs campaign-ideas on it directly (campaign-ideas then auto-completes
     ; the task). The local model is kept out of the fetch->work handoff because
     ; it cannot reliably copy a TASK_ID/MSG payload verbatim and loops on the
     ; fetch instead. Other agents get the plain TASK_ID/MSG summary to act on.
     ; Returns NO-TASKS (and does nothing else) when idle.
     (= (check-my-tasks)
          (if (== (instanceId) cda)
               (let $brief (py-call (agentverse.get_next_brief (instanceId)))
                    (if (== $brief "NO-TASKS")
                         "NO-TASKS"
                         (campaign-ideas $brief)))
               (let $summary (py-call (agentverse.get_pending_tasks_as_metta (instanceId)))
                    (if (== $summary "NO-TASKS")
                         "NO-TASKS"
                         (py-call (helper.normalize_string $summary))))))

     (= (complete-task $id $result)
          (py-call (agentverse.complete_task_summary $id $result)))

!(import_prolog_functions_from_file (library OmegaClaw-Core ./src/skills.pl) (shell first_char gc read_file_tail))

(= (metta $str)
   (let $code (sread $str)
        (repr (swrite (eval $code)))))

(= (pin $x)
   PIN-SUCCESS)
