% classes
\ProvidesClass{rewrite}
\LoadClass{article}
% packages
\usepackage[utf8]{inputenc}
\usepackage{fontspec}
\usepackage{geometry}
\geometry{
    a4paper,
    total={210mm,297mm},
    left=20mm,
    right=20mm,
    top=20mm,
    bottom=20mm,
}
\usepackage{xcolor}
% color
% \definecolor{titlecolor}{gray}{0.6}
% \definecolor{sectioncolor}{gray}{0.6}
\definecolor{titlecolor}{HTML}{9c2232}
\definecolor{sectioncolor}{HTML}{9c2232}
\definecolor{linkcol}{HTML}{001372}
\usepackage{fontawesome}
\usepackage[colorlinks=true, urlcolor=linkcol, linkcolor=linkcol, citecolor=linkcol]{hyperref}
\usepackage[explicit]{titlesec}
\usepackage{enumitem}
\usepackage{ragged2e}
\hyphenpenalty=10000
\tolerance=2000
% fonts
\defaultfontfeatures{Scale = MatchLowercase}
\setmainfont{TeX Gyre Heros}[Scale = 1.0]
% define 
\def\Plus{\texttt{+}}
\def\Minus{\texttt{-}}
% commands
\newcommand{\titlesection}[5]{
    \textcolor{titlecolor}{
        \centering{
            \fontsize{25pt}{60pt} \selectfont \textbf{#1} \\
            \vspace{5pt}
            \fontsize{12pt}{10pt} \selectfont 
            \faMobilePhone \hspace{1pt} #2
            \hspace{5pt} $\bullet$ \hspace{5pt}
            \faEnvelope \hspace{1pt} 
            \href{mailto:#3}{\textcolor{titlecolor}{#3}} \\
            \vspace{5pt} 
            \faLink \hspace{1pt} \href{https://#4}{\textcolor{titlecolor}{#4}}
            \hspace{10pt}
            \faLink \hspace{1pt} \href{https://#5}{\textcolor{titlecolor}{#5}} \\
        } 
    }
}

\newcommand{\titlesectionnew}[5]{
    \textcolor{titlecolor}{
        \centering{
            \fontsize{25pt}{60pt} \selectfont \textbf{#1} \\
            \vspace{5pt}
            \fontsize{10pt}{10pt} \selectfont 
            #2 $\bullet$
            \href{mailto:#3}{\textcolor{titlecolor}{#3}} $\bullet$
            \href{https://#4}{\textcolor{titlecolor}{Linkedin}} $\bullet$
            \href{https://#5}{\textcolor{titlecolor}{Github}} \\
        } 
    }
}

\newcommand{\workentry}[4]{
    \textbf{#1} \hfill {\normalfont #3} \\
    {\normalfont \emph{#2}} \hfill 
    {\footnotesize \normalfont \emph{#4}}
}

\newcommand{\workentrynew}[4]{%
    {\large\textbf{#1}}, {\normalfont\emph{#2}} \hfill {\normalfont #3}, {\normalfont{#4}}%
}

\newcommand{\projectentry}[2]{%
    \vspace{1pt} % small space before
    {$\bullet$ \hspace{2pt} \textbf{#1} \hfill} 
    {\footnotesize \normalfont \emph{#2}}%
    \vspace{0.5pt} % small space after
}
\newcommand{\skillentry}[1]{
     \subsection*{$\bullet$ \hspace{2pt} #1}
}