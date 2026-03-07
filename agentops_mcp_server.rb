class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/82/fe/a46e63d989f1da402ef6390346adcd56788f13d715d22dd0e2035b5f8ad1/agentops_mcp_server-0.4.1.tar.gz"
  sha256 "1309840082d64b51e611551f5db3c13c9507fa464bb830ae4804c710c3845e7c"
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
