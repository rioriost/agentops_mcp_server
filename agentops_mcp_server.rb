class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/ac/20/13077c15875b35f7363edf0f9c75a10de495a754f18a80b11a6baf2d186f/agentops_mcp_server-0.4.13.tar.gz"
  sha256 "dd562f9e959d558b999132d5abf943160f1f895490e5a5f3045b22bd082a4dc7"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
