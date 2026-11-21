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

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_projects (
    id integer NOT NULL,
    user_id integer,
    title character varying(255) NOT NULL,
    status character varying(50) NOT NULL,
    match_rate double precision,
    total_positions integer,
    created_at timestamp without time zone,
    object_name character varying(255),
    vor_filename character varying(255),
    lsr_filename character varying(255),
    matched_count integer,
    discrepancy_count integer,
    total_financial_risk double precision
);


--
-- Name: audit_projects_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_projects_id_seq
    AS integer
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
    id integer NOT NULL,
    project_id integer NOT NULL,
    doc_type character varying(50) NOT NULL,
    filename character varying(255) NOT NULL,
    row_count integer,
    uploaded_at timestamp without time zone
);


--
-- Name: documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.documents_id_seq
    AS integer
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
    id integer NOT NULL,
    project_id integer NOT NULL,
    vor_name text NOT NULL,
    decision character varying(100) NOT NULL,
    confidence double precision,
    prompt_tokens integer,
    completion_tokens integer,
    cost_rub double precision,
    created_at timestamp without time zone
);


--
-- Name: llm_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.llm_logs_id_seq
    AS integer
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
    id integer NOT NULL,
    project_id integer NOT NULL,
    vor_num character varying(50),
    lsr_num character varying(50),
    upper_status character varying(50) NOT NULL,
    detail_class character varying(100),
    text_sim double precision,
    qty_vor double precision,
    qty_lsr double precision,
    unit_price double precision,
    financial_risk double precision,
    formulation_warn boolean,
    user_decision character varying(50),
    row_num integer,
    vor_name text NOT NULL,
    lsr_name text,
    code character varying(100),
    unit character varying(50),
    is_ai boolean,
    explanation text
);


--
-- Name: match_results_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.match_results_id_seq
    AS integer
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
    created_at timestamp without time zone
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
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_audit_projects_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_projects_id ON public.audit_projects USING btree (id);


--
-- Name: ix_audit_projects_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_projects_user_id ON public.audit_projects USING btree (user_id);


--
-- Name: ix_documents_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_documents_id ON public.documents USING btree (id);


--
-- Name: ix_documents_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_documents_project_id ON public.documents USING btree (project_id);


--
-- Name: ix_llm_logs_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_logs_id ON public.llm_logs USING btree (id);


--
-- Name: ix_llm_logs_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_logs_project_id ON public.llm_logs USING btree (project_id);


--
-- Name: ix_match_results_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_match_results_id ON public.match_results USING btree (id);


--
-- Name: ix_match_results_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_match_results_project_id ON public.match_results USING btree (project_id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_id ON public.users USING btree (id);


--
-- Name: audit_projects audit_projects_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_projects
    ADD CONSTRAINT audit_projects_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: documents documents_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.audit_projects(id) ON DELETE CASCADE;


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

