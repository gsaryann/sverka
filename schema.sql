--
-- PostgreSQL database dump
--

-- Dumped from database version 17rc1
-- Dumped by pg_dump version 17rc1

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: update_audit_project_aggregates(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_audit_project_aggregates() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
            DECLARE
                v_project_id bigint;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    v_project_id := OLD.project_id;
                ELSE
                    v_project_id := NEW.project_id;
                END IF;

                UPDATE audit_projects
                SET
                    total_positions = sub.total_pos,
                    matched_count = sub.matched_cnt,
                    discrepancy_count = sub.disc_cnt,
                    total_financial_risk = sub.tot_risk,
                    match_rate = CASE WHEN sub.total_pos > 0 
                                      THEN ROUND((sub.matched_cnt::numeric / sub.total_pos::numeric) * 100, 2)
                                      ELSE 0.00 END
                FROM (
                    SELECT 
                        COUNT(*) AS total_pos,
                        COUNT(*) FILTER (WHERE upper_status = 'ok') AS matched_cnt,
                        COUNT(*) FILTER (WHERE upper_status IN ('diff', 'part')) AS disc_cnt,
                        COALESCE(SUM(financial_risk), 0.00) AS tot_risk
                    FROM match_results
                    WHERE project_id = v_project_id
                ) sub
                WHERE id = v_project_id;

                RETURN NULL;
            END;
            $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_projects (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    title character varying(255) NOT NULL,
    status character varying(50) NOT NULL,
    match_rate numeric(5,2) NOT NULL,
    total_positions integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    object_name character varying(255),
    vor_filename character varying(255),
    lsr_filename character varying(255),
    matched_count integer NOT NULL,
    discrepancy_count integer NOT NULL,
    total_financial_risk numeric(14,2) NOT NULL,
    CONSTRAINT check_project_discrepancy_count CHECK ((discrepancy_count >= 0)),
    CONSTRAINT check_project_match_rate CHECK (((match_rate >= (0)::numeric) AND (match_rate <= (100)::numeric))),
    CONSTRAINT check_project_matched_count CHECK ((matched_count >= 0)),
    CONSTRAINT check_project_status CHECK (((status)::text = ANY ((ARRAY['completed'::character varying, 'processing'::character varying, 'draft'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT check_project_total_financial_risk CHECK ((total_financial_risk >= (0)::numeric)),
    CONSTRAINT check_project_total_positions CHECK ((total_positions >= 0))
);


--
-- Name: COLUMN audit_projects.match_rate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_projects.match_rate IS 'Процент совпадения по проекту (шкала 0.00..100.00%)';


--
-- Name: audit_projects_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_projects_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_projects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_projects_id_seq OWNED BY public.audit_projects.id;


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    doc_type character varying(50) NOT NULL,
    filename character varying(255) NOT NULL,
    row_count integer NOT NULL,
    uploaded_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT check_doc_row_count CHECK ((row_count >= 0)),
    CONSTRAINT check_doc_type CHECK (((doc_type)::text = ANY ((ARRAY['VOR'::character varying, 'LSR'::character varying, 'ACT'::character varying, 'DOC'::character varying])::text[])))
);


--
-- Name: documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.documents_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.documents_id_seq OWNED BY public.documents.id;


--
-- Name: llm_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_logs (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    match_result_id bigint,
    vor_name text,
    decision character varying(100) NOT NULL,
    confidence numeric(5,4) NOT NULL,
    prompt_tokens integer NOT NULL,
    completion_tokens integer NOT NULL,
    cost_rub numeric(14,6) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT check_llm_completion_tokens CHECK ((completion_tokens >= 0)),
    CONSTRAINT check_llm_confidence CHECK (((confidence >= (0)::numeric) AND (confidence <= 1.0))),
    CONSTRAINT check_llm_cost_rub CHECK ((cost_rub >= (0)::numeric)),
    CONSTRAINT check_llm_prompt_tokens CHECK ((prompt_tokens >= 0))
);


--
-- Name: COLUMN llm_logs.confidence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.llm_logs.confidence IS 'Уверенность LLM-модели в решении (шкала 0.0000..1.0000)';


--
-- Name: COLUMN llm_logs.cost_rub; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.llm_logs.cost_rub IS 'Стоимость вызова в рублях с микрокопейками (до 6 знаков)';


--
-- Name: llm_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.llm_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: llm_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.llm_logs_id_seq OWNED BY public.llm_logs.id;


--
-- Name: match_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.match_results (
    id bigint NOT NULL,
    project_id bigint NOT NULL,
    vor_num character varying(50),
    lsr_num character varying(50),
    upper_status character varying(50) NOT NULL,
    detail_class character varying(100),
    text_sim numeric(5,4),
    qty_vor numeric(14,3),
    qty_lsr numeric(14,3),
    unit_price numeric(14,2),
    financial_risk numeric(14,2) NOT NULL,
    formulation_warn boolean NOT NULL,
    user_decision character varying(50),
    row_num integer NOT NULL,
    vor_name text NOT NULL,
    lsr_name text,
    code character varying(100),
    unit character varying(50),
    is_ai boolean NOT NULL,
    explanation text,
    CONSTRAINT check_match_financial_risk CHECK ((financial_risk >= (0)::numeric)),
    CONSTRAINT check_match_text_sim CHECK (((text_sim IS NULL) OR ((text_sim >= (0)::numeric) AND (text_sim <= 1.0)))),
    CONSTRAINT check_match_unit_price CHECK (((unit_price IS NULL) OR (unit_price >= (0)::numeric))),
    CONSTRAINT check_match_upper_status CHECK (((upper_status)::text = ANY ((ARRAY['ok'::character varying, 'part'::character varying, 'diff'::character varying, 'none'::character varying])::text[]))),
    CONSTRAINT check_match_user_decision CHECK ((((user_decision)::text = ANY ((ARRAY['yes'::character varying, 'no'::character varying])::text[])) OR (user_decision IS NULL)))
);


--
-- Name: COLUMN match_results.text_sim; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.match_results.text_sim IS 'Косинусное/текстовое сходство наименований (шкала 0.0000..1.0000)';


--
-- Name: COLUMN match_results.unit_price; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.match_results.unit_price IS 'Цена за единицу (руб.)';


--
-- Name: match_results_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.match_results_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: match_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.match_results_id_seq OWNED BY public.match_results.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying(120) NOT NULL,
    password_hash character varying(256) NOT NULL,
    full_name character varying(150) NOT NULL,
    role character varying(50) NOT NULL,
    company character varying(150),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT check_user_role CHECK (((role)::text = ANY ((ARRAY['estimator'::character varying, 'lead'::character varying, 'admin'::character varying])::text[])))
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: audit_projects id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_projects ALTER COLUMN id SET DEFAULT nextval('public.audit_projects_id_seq'::regclass);


--
-- Name: documents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents ALTER COLUMN id SET DEFAULT nextval('public.documents_id_seq'::regclass);


--
-- Name: llm_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_logs ALTER COLUMN id SET DEFAULT nextval('public.llm_logs_id_seq'::regclass);


--
-- Name: match_results id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.match_results ALTER COLUMN id SET DEFAULT nextval('public.match_results_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: audit_projects audit_projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_projects
    ADD CONSTRAINT audit_projects_pkey PRIMARY KEY (id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: llm_logs llm_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_logs
    ADD CONSTRAINT llm_logs_pkey PRIMARY KEY (id);


--
-- Name: match_results match_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.match_results
    ADD CONSTRAINT match_results_pkey PRIMARY KEY (id);


--
-- Name: match_results uq_match_results_id_project; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.match_results
    ADD CONSTRAINT uq_match_results_id_project UNIQUE (id, project_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_audit_projects_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_projects_user_created ON public.audit_projects USING btree (user_id, created_at DESC);


--
-- Name: ix_documents_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_documents_project_id ON public.documents USING btree (project_id);


--
-- Name: ix_llm_logs_match_result_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_logs_match_result_id ON public.llm_logs USING btree (match_result_id);


--
-- Name: ix_llm_logs_proj_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_logs_proj_created ON public.llm_logs USING btree (project_id, created_at);


--
-- Name: ix_match_results_proj_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_match_results_proj_status ON public.match_results USING btree (project_id, upper_status);


--
-- Name: ix_users_email_lower; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email_lower ON public.users USING btree (lower((email)::text));


--
-- Name: ux_match_results_proj_row; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_match_results_proj_row ON public.match_results USING btree (project_id, row_num);


--
-- Name: match_results trg_match_results_aggregates; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_match_results_aggregates AFTER INSERT OR DELETE OR UPDATE ON public.match_results FOR EACH ROW EXECUTE FUNCTION public.update_audit_project_aggregates();


--
-- Name: audit_projects audit_projects_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_projects
    ADD CONSTRAINT audit_projects_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: documents documents_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.audit_projects(id) ON DELETE CASCADE;


--
-- Name: llm_logs fk_llm_logs_match_result_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_logs
    ADD CONSTRAINT fk_llm_logs_match_result_project FOREIGN KEY (match_result_id, project_id) REFERENCES public.match_results(id, project_id) ON DELETE SET NULL (match_result_id);


--
-- Name: llm_logs llm_logs_match_result_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_logs
    ADD CONSTRAINT llm_logs_match_result_id_fkey FOREIGN KEY (match_result_id) REFERENCES public.match_results(id) ON DELETE SET NULL;


--
-- Name: llm_logs llm_logs_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_logs
    ADD CONSTRAINT llm_logs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.audit_projects(id) ON DELETE CASCADE;


--
-- Name: match_results match_results_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.match_results
    ADD CONSTRAINT match_results_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.audit_projects(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

